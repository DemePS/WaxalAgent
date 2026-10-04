"""Wolof speech on Soynade's API (model oolel-speech-v1), two routes:

  transcribe:      POST /v1/audio/transcriptions   Wolof speech -> Wolof text (multipart: file, model; optionally language)
  translate_audio: POST /v1/audio/translations     Wolof speech -> English text in ONE call; multipart exactly as in
                   Soynade's reference: file, source_language "wo", target_language, response_format "json", temperature
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

    def translate_audio(self, wav: bytes, source: str = "wo", target: str = "en") -> str:
        """Wolof speech straight to text in another language (one call instead of recognition then translation)."""
        data = {"source_language": source, "target_language": target, "response_format": "json",
                "temperature": os.environ.get("SOYNADE_TRANSLATE_TEMPERATURE") or "0"}
        response = self.client.post_file("audio/translations", {"file": ("audio.wav", wav, "audio/wav")}, data)
        return text_in(response, ("text", "translation", "translated_text"))
