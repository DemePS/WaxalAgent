"""Wolof speech by ElevenLabs: POST /v1/text-to-speech/{voice_id}?output_format=pcm_16000 (raw 16-bit 16 kHz mono, wrapped as WAV).

    {"text": ..., "model_id": "eleven_v4", "language_code": "wo"}

ELEVENLABS_VOICE_ID (any voice of your account; default: a premade voice), ELEVENLABS_TTS_MODEL (default eleven_v4),
ELEVENLABS_TTS_LANGUAGE (default wo; set it empty to leave the field out if ElevenLabs rejects it).
"""

import io
import os
import wave

from ..elevenlabs_api import ElevenLabsClient

DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"  # "Rachel", a premade voice every account has


class ElevenLabsSpeaker:
    def __init__(self, client: ElevenLabsClient | None = None) -> None:
        self.client = client or ElevenLabsClient()
        env = os.environ
        self.voice = env.get("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE
        self.model = env.get("ELEVENLABS_TTS_MODEL") or "eleven_v4"
        self.language = env.get("ELEVENLABS_TTS_LANGUAGE", "wo")

    def request_body(self, text: str) -> dict:
        body = {"text": text, "model_id": self.model}
        if self.language:
            body["language_code"] = self.language
        return body

    def speak(self, text: str) -> bytes:
        response = self.client.post(f"v1/text-to-speech/{self.voice}", params={"output_format": "pcm_16000"},
                                    json=self.request_body(text))
        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
            w.writeframes(response.content)
        return out.getvalue()
