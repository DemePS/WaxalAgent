"""Wolof speech: POST /v1/text-to-speech on Soynade's API (their Oolel-Voices model, default voice).

The request is the one in Soynade's reference:

    {"text": ..., "language": "wo", "output_format": "wav"}

and the answer is the WAV file itself. Optional tuning, sent only when set in the environment: SOYNADE_TTS_TEMPERATURE (0 for
the most stable voice), SOYNADE_TTS_EXAGGERATION, SOYNADE_TTS_CFG, SOYNADE_TTS_SEED (the same seed gives the same voice for
the same text); SOYNADE_TTS_LANGUAGE (default wo). The result is converted to 16 kHz mono WAV (ffmpeg).
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

RETRY_AFTER_SECONDS = 600
AUDIO_MAGIC = (b"RIFF", b"ID3", b"OggS", b"fLaC", b"FORM")


class SoynadeSpeaker:
    model = "oolel-voices"  # for display: the request has no model field

    def __init__(self, client: SoynadeClient | None = None) -> None:
        self.client = client or SoynadeClient()
        self._unavailable_until = 0.0
        self._reason = ""

    def request_body(self, text: str) -> dict:
        env = os.environ
        body = {"text": text, "language": env.get("SOYNADE_TTS_LANGUAGE") or "wo", "output_format": "wav"}
        for key, name, kind in (("temperature", "SOYNADE_TTS_TEMPERATURE", float), ("exaggeration", "SOYNADE_TTS_EXAGGERATION", float),
                                ("cfg_weight", "SOYNADE_TTS_CFG", float), ("seed", "SOYNADE_TTS_SEED", int)):
            if env.get(name):  # only when asked for: the reference's minimal request does not send them
                body[key] = kind(env[name])
        return body

    def speak(self, text: str) -> bytes:
        if (os.environ.get("SOYNADE_TTS") or "").lower() in ("off", "0", "false", "no"):
            raise SpeechUnavailable("Speech output is switched off (SOYNADE_TTS=off).")
        if time.monotonic() < self._unavailable_until:
            raise SpeechUnavailable(self._reason)
        try:
            response = self.client.post_json("text-to-speech", self.request_body(text))
            return audio.to_wav(audio_from(response, self.client.http))
        except SoynadeError as e:
            if "only text output" in str(e).lower() or e.status in (404, 501):
                self._reason = f"Soynade's API does not offer speech output for this key yet ({str(e)[:160]})."
                self._unavailable_until = time.monotonic() + RETRY_AFTER_SECONDS
                raise SpeechUnavailable(self._reason) from e
            raise


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
