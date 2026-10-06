"""ElevenLabs' hosted API (https://elevenlabs.io/docs/api-reference), plain HTTPS calls like the Soynade client:

    POST /v1/text-to-speech/{voice_id}   text -> speech       (model eleven_v4, the one that lists Wolof)
    POST /v1/speech-to-text              speech -> text       (model scribe_v1)

    ELEVENLABS_API_KEY    your key (xi-api-key header): never in the repository
    ELEVENLABS_BASE_URL   default https://api.elevenlabs.io

Retries, rate limits and the cooldown are the shared policy (waxal_agent/http_calls.py): a rate limit is not waited out (the call
fails with ElevenLabs' own message and no call is made for ELEVENLABS_COOLDOWN seconds, default 30); a server or network error is
tried twice.
"""

from __future__ import annotations

import os

import httpx

from .http_calls import CallPolicy
from .soynade_api import SoynadeError

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
        # The shared policy (waxal_agent/http_calls.py): a 429 is not waited out (no retry), then no call for ELEVENLABS_COOLDOWN
        # seconds (default 30); a quota refusal (402) too; a server or network error is tried `attempts` times in all.
        self.policy = CallPolicy(
            "ElevenLabs call", ElevenLabsError, detail=_detail, retries=0, server_retries=attempts - 1, network_retries=attempts - 1,
            cooldown=cooldown if cooldown is not None else float(os.environ.get("ELEVENLABS_COOLDOWN") or 30),
            quota_statuses=(402,))

    def post(self, path: str, **options) -> httpx.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        return self.policy.run(lambda: self.http.post(url, headers={"xi-api-key": self.api_key}, **options), url)

    def stream_post(self, path: str, **options) -> httpx.Response:
        """Like post(), but the body is not read: the caller iterates `iter_bytes()` and closes the response. The status is checked
        (and an error body read) before it returns, under the same policy as post()."""
        url = f"{self.base_url}/{path.lstrip('/')}"

        def send() -> httpx.Response:
            request = self.http.build_request("POST", url, headers={"xi-api-key": self.api_key}, **options)
            response = self.http.send(request, stream=True)
            if response.status_code != 200:
                response.read()  # the policy reads the error detail
            return response
        return self.policy.run(send, url)


def _detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return " ".join(response.text[:300].split())
    detail = data.get("detail", data) if isinstance(data, dict) else data
    if isinstance(detail, dict):
        detail = detail.get("message") or detail
    return str(detail)[:500]
