"""Wolof speech through Soynade's hosted API.

Two routes are tried, both from the OpenAI-compatible API family their base URL belongs to (neither is confirmed by
Soynade's pages that I could read: `scripts/check_api.py speak "..."` shows what actually works for your key):
  1. POST {base}/audio/speech  {model, input, voice, response_format}   -> audio bytes
  2. POST {base}/chat/completions with modalities ["text","audio"] and audio {voice, format}  -> message.audio.data (base64)
Settings: SOYNADE_TTS_MODEL (else found in the model list), SOYNADE_TTS_VOICE (default "default"), SOYNADE_TTS_ROUTE
("speech" or "chat" to force one; default: speech first, chat when that route does not exist).
The result is always converted to 16 kHz mono WAV (ffmpeg), whatever Soynade returns.
"""

import base64
import os

from .. import audio
from ..soynade_api import SoynadeClient, SoynadeError
from ..soynade_models import pick


class SoynadeSpeaker:
    def __init__(self, client: SoynadeClient | None = None, model: str | None = None, voice: str | None = None) -> None:
        self.client = client or SoynadeClient()
        self._model = model or os.environ.get("SOYNADE_TTS_MODEL")
        self.voice = voice or os.environ.get("SOYNADE_TTS_VOICE") or "default"
        self.route = (os.environ.get("SOYNADE_TTS_ROUTE") or "").lower()

    @property
    def model(self) -> str:
        if self._model is None:
            self._model = pick(self.client, "speech output", "SOYNADE_TTS_MODEL")
        return self._model

    def speak(self, text: str) -> bytes:
        routes = [self.route] if self.route in ("speech", "chat") else ["speech", "chat"]
        for index, route in enumerate(routes):
            try:
                raw = self._speech(text) if route == "speech" else self._chat(text)
            except SoynadeError as e:
                if index + 1 < len(routes) and e.status in (404, 405):  # this route does not exist: try the next
                    continue
                raise
            return audio.to_wav(raw)
        raise SoynadeError("Soynade has no speech-output route that works with this key.")

    def _speech(self, text: str) -> bytes:
        response = self.client.raw("audio/speech", {"model": self.model, "input": text, "voice": self.voice,
                                                    "response_format": "wav"})
        return response.content

    def _chat(self, text: str) -> bytes:
        completion = self.client.chat(self.model, [{"role": "user", "content": text}], modalities=["text", "audio"],
                                      audio={"voice": self.voice, "format": "wav"})
        try:
            return base64.b64decode(completion["choices"][0]["message"]["audio"]["data"])
        except (KeyError, IndexError, TypeError, ValueError):
            raise SoynadeError(f"Soynade's answer has no audio: {str(completion)[:200]}")
