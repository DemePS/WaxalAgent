"""Soynade's hosted API: an OpenAI-compatible chat API (https://developers.soynade.ai).

    SOYNADE_API_KEY     your key (from Soynade's console): never in the repository
    SOYNADE_BASE_URL    default https://api.soynade.ai/openai/v1

Requests are plain HTTPS calls (httpx), so the OpenAI SDK is not needed, and they can be tested with recorded responses.
Everything here is what Soynade's quickstart shows: POST {base}/chat/completions with a Bearer key.
"""

from __future__ import annotations

import logging
import os
import threading
import time

import httpx

log = logging.getLogger("waxal.soynade")

DEFAULT_BASE_URL = "https://api.soynade.ai/openai/v1"
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
        # Rate limits (HTTP 429) are normal on a free or small plan: wait as the server says, retry a few times, and
        # never send two calls closer than min_interval seconds (SOYNADE_MIN_INTERVAL, default 0.5; SOYNADE_RETRIES, default 4).
        self.retries = retries if retries is not None else int(os.environ.get("SOYNADE_RETRIES") or 4)
        self.backoff = backoff
        self.min_interval = (min_interval if min_interval is not None
                             else float(os.environ.get("SOYNADE_MIN_INTERVAL") or 0.5))
        self._gate = threading.Lock()
        self._last_call = 0.0

    def chat(self, model: str, messages: list[dict], **options) -> dict:
        """POST /chat/completions; returns the response JSON. Retries rate limits and server errors."""
        return self._request("POST", "chat/completions", {"model": model, "messages": messages, **options}).json()

    def models(self) -> list[str]:
        """GET /models (the OpenAI-compatible list): the ids of the models your key can use."""
        response = self._request("GET", "models")
        try:
            return sorted(str(m["id"]) for m in response.json()["data"])
        except (KeyError, TypeError, ValueError):
            raise SoynadeError(f"Unexpected answer from Soynade's model list: {response.text[:200]}")

    def raw(self, path: str, body: dict) -> httpx.Response:
        """POST any other route of the API (e.g. audio/speech); the answer is returned as is, errors raise."""
        return self._request("POST", path, body)

    def _throttle(self) -> None:
        with self._gate:
            wait = self._last_call + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def _request(self, method: str, path: str, body: dict | None = None) -> httpx.Response:
        last, wait = "", 0.0
        for attempt in range(self.retries + 1):
            self._throttle()
            try:
                response = self.http.request(method, f"{self.base_url}/{path}", json=body,
                                             headers={"Authorization": f"Bearer {self.api_key}"})
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
        hint = (" The rate limit of your Soynade plan is reached: wait a minute, or check the limits in Soynade's console."
                if last.startswith("HTTP 429") else "")
        raise SoynadeError(f"Soynade API call failed ({path}): {last}.{hint}", status=429 if last.startswith("HTTP 429") else None)

    def text_of(self, completion: dict) -> str:
        try:
            content = completion["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise SoynadeError(f"Unexpected answer from Soynade: {str(completion)[:200]}")
        return (content or "").strip()


def _retry_after(response: httpx.Response) -> float:
    """The server's Retry-After header (seconds), 0 when absent or not a number."""
    try:
        return max(0.0, float(response.headers.get("retry-after", "0")))
    except ValueError:
        return 0.0


def _detail(response: httpx.Response) -> str:
    try:
        data = response.json()
        error = data.get("error", data) if isinstance(data, dict) else data
        return str(error.get("message", error) if isinstance(error, dict) else error)[:300]
    except ValueError:
        return response.text[:300]
