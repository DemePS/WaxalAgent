"""ElevenLabs' hosted API (https://elevenlabs.io/docs/api-reference), plain HTTPS calls like the Soynade client:

    POST /v1/text-to-speech/{voice_id}   text -> speech       (model eleven_v4, the one that lists Wolof)
    POST /v1/speech-to-text              speech -> text       (model scribe_v1)

    ELEVENLABS_API_KEY    your key (xi-api-key header): never in the repository
    ELEVENLABS_BASE_URL   default https://api.elevenlabs.io

A rate limit or a quota refusal is not waited out in a loop: the call fails with ElevenLabs' own message and no further call is
made for ELEVENLABS_COOLDOWN seconds (default 30). A server error (5xx) or a network error is tried twice.
"""

from __future__ import annotations

import logging
import os
import time

import httpx

from .soynade_api import SoynadeError

log = logging.getLogger("waxal.elevenlabs")

DEFAULT_BASE_URL = "https://api.elevenlabs.io"


class ElevenLabsError(SoynadeError):
    """ElevenLabs did not give an answer. (It is a SoynadeError so the code that reports a failing speech service handles both.)"""


class ElevenLabsClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, http: httpx.Client | None = None,
                 attempts: int = 2, cooldown: float | None = None) -> None:
        self.api_key = api_key or os.environ.get("ELEVENLABS_API_KEY") or ""
        if not self.api_key:
            raise ElevenLabsError("ELEVENLABS_API_KEY is not set (create a key in ElevenLabs' settings).")
        self.base_url = (base_url or os.environ.get("ELEVENLABS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.http = http or httpx.Client(timeout=httpx.Timeout(120, connect=15))
        self.attempts = attempts
        self.cooldown = cooldown if cooldown is not None else float(os.environ.get("ELEVENLABS_COOLDOWN") or 30)
        self._cooldown_until = 0.0

    def post(self, path: str, **options) -> httpx.Response:
        remaining = self._cooldown_until - time.monotonic()
        if remaining > 0:
            raise ElevenLabsError(f"ElevenLabs refused the last call (limit or quota): not calling again for {remaining:.0f} s.", status=429)
        url, last = f"{self.base_url}/{path.lstrip('/')}", ""
        for attempt in range(1, self.attempts + 1):
            started = time.monotonic()
            try:
                response = self.http.post(url, headers={"xi-api-key": self.api_key}, **options)
            except httpx.TransportError as e:
                last = f"network error: {type(e).__name__}: {e}"
                log.warning("%s: %s after %.1f s", path, last, time.monotonic() - started)
                continue
            log.info("%s -> HTTP %s in %.1f s (attempt %d)", path, response.status_code, time.monotonic() - started, attempt)
            if response.status_code == 200:
                return response
            last = f"HTTP {response.status_code}: {_detail(response)}"
            if response.status_code in (401, 402, 429):  # a bad key, no credit, or a rate limit: more calls only make it worse
                if response.status_code != 401:
                    self._cooldown_until = time.monotonic() + self.cooldown
                raise ElevenLabsError(f"ElevenLabs call failed ({url}): {last}", status=response.status_code)
            if response.status_code < 500:
                raise ElevenLabsError(f"ElevenLabs call failed ({url}): {last}", status=response.status_code)
        raise ElevenLabsError(f"ElevenLabs call failed ({url}): {last}")


def _detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return " ".join(response.text[:300].split())
    detail = data.get("detail", data) if isinstance(data, dict) else data
    if isinstance(detail, dict):
        detail = detail.get("message") or detail
    return str(detail)[:500]
