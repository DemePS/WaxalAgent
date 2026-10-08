"""Wolof speech recognition by ElevenLabs: POST /v1/speech-to-text (multipart: file, model_id, language_code) -> {"text": ...}.

ELEVENLABS_STT_MODEL (default scribe_v1), ELEVENLABS_STT_LANGUAGE (default wol; set it empty to let ElevenLabs detect the
language). There is no direct speech-to-English route here: the Wolof text is translated to English afterwards (by Claude).
"""

import os

from ..elevenlabs_api import ElevenLabsClient
from ..language import Language
from ..soynade_api import text_in


class ElevenLabsListener:
    def __init__(self, client: ElevenLabsClient | None = None, language: Language | None = None) -> None:
        self.client = client or ElevenLabsClient()
        language = language or Language.from_env()
        env = os.environ
        self.model = env.get("ELEVENLABS_STT_MODEL") or "scribe_v1"
        # Wolof, the language of the person; with WAXAL_TRANSLATION=off the language of reply_language (fr: fra)
        self.language = env.get("ELEVENLABS_STT_LANGUAGE", language.stt_code)

    def transcribe(self, wav: bytes) -> str:
        data = {"model_id": self.model, "tag_audio_events": "false"}
        if self.language:
            data["language_code"] = self.language
        response = self.client.post("v1/speech-to-text", files={"file": ("audio.wav", wav, "audio/wav")}, data=data)
        return text_in(response, ("text",))
