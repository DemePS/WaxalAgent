"""Wolof speech recognition: POST /v1/audio/transcriptions on Soynade's API (model oolel-speech-v1).

Sent as a multipart upload, the way a transcription route is usually shaped: file = the WAV, model = the model; with
SOYNADE_ASR_LANGUAGE (e.g. wo) a `language` field too. The answer's `text` is the transcription.
"""

import os

from ..soynade_api import SoynadeClient, text_in

DEFAULT_MODEL = "oolel-speech-v1"


class SoynadeListener:
    def __init__(self, client: SoynadeClient | None = None, model: str | None = None) -> None:
        self.client = client or SoynadeClient()
        self.model = model or os.environ.get("SOYNADE_ASR_MODEL") or DEFAULT_MODEL

    def transcribe(self, wav: bytes) -> str:
        data = {"model": self.model}
        if os.environ.get("SOYNADE_ASR_LANGUAGE"):
            data["language"] = os.environ["SOYNADE_ASR_LANGUAGE"]
        response = self.client.post_file("audio/transcriptions", {"file": ("audio.wav", wav, "audio/wav")}, data)
        return text_in(response, ("text", "transcription", "transcript"))
