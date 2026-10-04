"""Wolof speech: POST /v1/text-to-speech on Soynade's API (model oolel-voices, its default voice).

The documentation lists the route and the model, not the fields: the JSON sent is {"model": "oolel-voices", "input": text}
(plus "voice" when SOYNADE_TTS_VOICE is set); when the server rejects it (HTTP 400 / 422) {"model", "text"} is tried, and
both messages are shown if neither works. The answer is audio bytes, or JSON holding the audio (base64 under audio /
audio_base64 / data, or a url to download). Everything is converted to 16 kHz mono WAV (ffmpeg).
While Soynade says audio output is not offered ("Only text output is supported during launch") or switched off
(SOYNADE_TTS=off), a reply stays text only and the API is not asked again for ten minutes.
"""

import base64
import os
import time

import httpx

from .. import audio
from ..soynade_api import SoynadeClient, SoynadeError
from .base import SpeechUnavailable

DEFAULT_MODEL = "oolel-voices"
RETRY_AFTER_SECONDS = 600
AUDIO_MAGIC = (b"RIFF", b"ID3", b"OggS", b"fLaC", b"FORM")


class SoynadeSpeaker:
    def __init__(self, client: SoynadeClient | None = None, model: str | None = None, voice: str | None = None) -> None:
        self.client = client or SoynadeClient()
        self.model = model or os.environ.get("SOYNADE_TTS_MODEL") or DEFAULT_MODEL
        self.voice = voice or os.environ.get("SOYNADE_TTS_VOICE") or None
        self._key = None
        self._unavailable_until = 0.0
        self._reason = ""

    def speak(self, text: str) -> bytes:
        if (os.environ.get("SOYNADE_TTS") or "").lower() in ("off", "0", "false", "no"):
            raise SpeechUnavailable("Speech output is switched off (SOYNADE_TTS=off).")
        if time.monotonic() < self._unavailable_until:
            raise SpeechUnavailable(self._reason)
        try:
            return audio.to_wav(self._audio(text))
        except SoynadeError as e:
            lowered = str(e).lower()
            if "only text output" in lowered or e.status in (404, 501):
                self._reason = f"Soynade's API does not offer speech output for this key yet ({str(e)[:160]})."
                self._unavailable_until = time.monotonic() + RETRY_AFTER_SECONDS
                raise SpeechUnavailable(self._reason) from e
            raise

    def _audio(self, text: str) -> bytes:
        keys = [self._key] if self._key else ["input", "text"]
        errors = []
        for key in keys:
            body = {"model": self.model, key: text}
            if self.voice:
                body["voice"] = self.voice
            try:
                response = self.client.post_json("text-to-speech", body)
            except SoynadeError as e:
                if e.status in (400, 422) and "only text output" not in str(e).lower() and not self._key:
                    errors.append(f"{sorted(body)}: {e}")
                    continue
                raise
            self._key = key
            return audio_from(response, self.client.http)
        raise SoynadeError("Soynade's /text-to-speech rejected both request shapes:\n  " + "\n  ".join(errors), status=422)


def audio_from(response: httpx.Response, http: httpx.Client) -> bytes:
    """The audio of a text-to-speech answer: the body itself, or JSON holding it (base64, or a url to download)."""
    if response.headers.get("content-type", "").startswith("audio/") or response.content[:4] in AUDIO_MAGIC:
        return response.content
    try:
        data = response.json()
    except ValueError:
        raise SoynadeError(f"Soynade's text-to-speech answer is not audio: {response.text[:200]}")
    for key in ("audio", "audio_base64", "data", "b64_json"):
        value = data.get(key) if isinstance(data, dict) else None
        if isinstance(value, str) and value:
            try:
                return base64.b64decode(value)
            except ValueError:
                pass
    url = (data.get("url") or data.get("audio_url")) if isinstance(data, dict) else None
    if isinstance(url, str):
        download = http.get(url)
        download.raise_for_status()
        return download.content
    raise SoynadeError(f"Soynade's text-to-speech answer holds no audio I recognise: {str(data)[:200]}")
