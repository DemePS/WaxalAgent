"""Wolof speech recognition through Soynade's hosted speech model (no model to host)."""

import base64
import os

from ..soynade_api import SoynadeClient

DEFAULT_MODEL = "oolel-speech-v1"
PROMPT = "Transcribe this audio. Reply with the transcription only."


class SoynadeListener:
    def __init__(self, client: SoynadeClient | None = None, model: str | None = None) -> None:
        self.client = client or SoynadeClient()
        self.model = model or os.environ.get("SOYNADE_ASR_MODEL") or DEFAULT_MODEL

    def transcribe(self, wav: bytes) -> str:
        audio = base64.b64encode(wav).decode("ascii")
        completion = self.client.chat(
            self.model,
            [{"role": "user", "content": [
                {"type": "input_audio", "input_audio": {"data": audio, "format": "wav"}},
                {"type": "text", "text": PROMPT}]}],
            modalities=["text"], temperature=0, max_tokens=512)
        return self.client.text_of(completion)
