"""Soynade's hosted API, called directly on its own routes (https://developers.soynade.ai):

    POST /v1/audio/transcriptions   Wolof speech -> text        (model oolel-speech-v1)
    POST /v1/translations           text translation            (model oolel-speech-v1)
    POST /v1/text-to-speech         Wolof text -> speech        (model oolel-voices, default voice)

    SOYNADE_API_KEY     your key (from Soynade's console): never in the repository
    SOYNADE_BASE_URL    default https://api.soynade.ai/v1

Plain HTTPS calls (httpx): no SDK, no chat client, and everything can be tested with recorded responses. Soynade's
documentation lists the routes and models but I could not read the request fields: each engine says what it sends, and a
rejection shows Soynade's own message so a field name can be corrected from it.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time

import httpx

log = logging.getLogger("waxal.soynade")

DEFAULT_BASE_URL = "https://api.soynade.ai/v1"
RETRY_STATUS = (429, 500, 502, 503, 504)


class SoynadeError(Exception):
    """The Soynade API did not give an answer (the message is meant to be read by the operator, not the end user)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class SoynadeClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, http: httpx.Client | None = None,
                 retries: int | None = None, backoff: float = 2.0, min_interval: float | None = None) -> None:
        self.api_key = api_key or os.environ.get("SOYNADE_API_KEY") or ""
        if not self.api_key:
            raise SoynadeError("SOYNADE_API_KEY is not set (create a key in Soynade's console).")
        self.base_url = (base_url or os.environ.get("SOYNADE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.http = http or httpx.Client(timeout=httpx.Timeout(120, connect=15))
        # Rate limits (HTTP 429) are normal on a small plan: wait as the server says, retry a few times, and never send two
        # calls closer than min_interval seconds (SOYNADE_MIN_INTERVAL, default 0.5; SOYNADE_RETRIES, default 4).
        self.retries = retries if retries is not None else int(os.environ.get("SOYNADE_RETRIES") or 4)
        self.backoff = backoff
        self.min_interval = (min_interval if min_interval is not None
                             else float(os.environ.get("SOYNADE_MIN_INTERVAL") or 0.5))
        self._gate = threading.Lock()
        self._last_call = 0.0

    def post_json(self, path: str, body: dict) -> httpx.Response:
        return self._request("POST", path, json=body)

    def post_file(self, path: str, files: dict, data: dict | None = None) -> httpx.Response:
        """A multipart upload (an audio file plus fields)."""
        return self._request("POST", path, files=files, data=data or {})

    def _throttle(self) -> None:
        with self._gate:
            wait = self._last_call + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def _request(self, method: str, path: str, **options) -> httpx.Response:
        last, wait = "", 0.0
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                response = self.http.request(method, f"{self.base_url}/{path}", headers={"Authorization": f"Bearer {self.api_key}"},
                                             **options)
            except httpx.TransportError as e:
                last = f"network error: {type(e).__name__}: {e}"
            else:
                if response.status_code == 200:
                    return response
                last = f"HTTP {response.status_code}: {_detail(response)}"
                if response.status_code not in RETRY_STATUS:
                    raise SoynadeError(f"Soynade API call failed ({path}): {last}", status=response.status_code)
                wait = _retry_after(response)
            if attempt < self.retries:
                time.sleep(min(max(wait, self.backoff * (2 ** attempt)), 30))
                wait = 0.0
        limited = last.startswith("HTTP 429")
        hint = (" The rate limit of your Soynade plan is reached: wait a minute, or check the limits in Soynade's console."
                if limited else "")
        raise SoynadeError(f"Soynade API call failed ({path}): {last}.{hint}", status=429 if limited else None)


def text_in(response: httpx.Response, keys: tuple[str, ...]) -> str:
    """The text of an answer: the first of `keys` found in its JSON (also one level down), or a plain-text body."""
    try:
        data = response.json()
    except ValueError:
        return response.text.strip()
    found = _find(data, keys)
    if found is None:
        raise SoynadeError(f"Unexpected answer from Soynade: {str(data)[:200]}")
    return found.strip()


def _find(data, keys):
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        for key in keys:
            if isinstance(data.get(key), str):
                return data[key]
        for value in data.values():
            if isinstance(value, (dict, list)):
                found = _find(value, keys)
                if found is not None:
                    return found
    if isinstance(data, list):
        for item in data:
            found = _find(item, keys)
            if found is not None:
                return found
    return None


def _retry_after(response: httpx.Response) -> float:
    try:
        return max(0.0, float(response.headers.get("retry-after", "0")))
    except ValueError:
        return 0.0


def _detail(response: httpx.Response) -> str:
    try:
        data = response.json()
        error = data.get("error", data) if isinstance(data, dict) else data
        if isinstance(error, dict):
            extra = {k: v for k, v in error.items() if k not in ("message", "detail", "title")}
            error = error.get("message") or error.get("detail") or error.get("title") or error
            if extra:  # per-field validation errors say which field is wrong
                error = f"{error} {extra}"
        elif isinstance(data, dict) and len(data) > 1:
            error = data
        return str(error)[:800]
    except ValueError:
        title = re.search(r"<title>(.*?)</title>", response.text, re.S | re.I)  # an HTML error page (e.g. 502 from the gateway)
        return " ".join((title.group(1) if title else response.text[:800]).split())
