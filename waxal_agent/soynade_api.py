"""Soynade's hosted API: an OpenAI-compatible chat API (https://developers.soynade.ai).

    SOYNADE_API_KEY     your key (from Soynade's console): never in the repository
    SOYNADE_BASE_URL    default https://api.soynade.ai/openai/v1

Requests are plain HTTPS calls (httpx), so the OpenAI SDK is not needed, and they can be tested with recorded responses.
Everything here is what Soynade's quickstart shows: POST {base}/chat/completions with a Bearer key.
"""

from __future__ import annotations

import logging
import os
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
                 retries: int = 2, backoff: float = 1.0) -> None:
        self.api_key = api_key or os.environ.get("SOYNADE_API_KEY") or ""
        if not self.api_key:
            raise SoynadeError("SOYNADE_API_KEY is not set (create a key in Soynade's console).")
        self.base_url = (base_url or os.environ.get("SOYNADE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.http = http or httpx.Client(timeout=httpx.Timeout(120, connect=15))
        self.retries, self.backoff = retries, backoff

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

    def _request(self, method: str, path: str, body: dict | None = None) -> httpx.Response:
        last = ""
        for attempt in range(self.retries + 1):
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
            if attempt < self.retries:
                time.sleep(self.backoff * (2 ** attempt))
        raise SoynadeError(f"Soynade API call failed ({path}): {last}")

    def text_of(self, completion: dict) -> str:
        try:
            content = completion["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise SoynadeError(f"Unexpected answer from Soynade: {str(completion)[:200]}")
        return (content or "").strip()


def _detail(response: httpx.Response) -> str:
    try:
        data = response.json()
        error = data.get("error", data) if isinstance(data, dict) else data
        return str(error.get("message", error) if isinstance(error, dict) else error)[:300]
    except ValueError:
        return response.text[:300]
