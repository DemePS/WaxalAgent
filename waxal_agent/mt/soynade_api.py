"""Wolof <-> English translation: POST /v1/translations on Soynade's API.

Request (JSON, no model field):
    {"source_language": "wo", "target_language": "en", "temperature": 0.1, "text": "..."}
The answer's text is read from translation / translated_text / text / output (or a plain-text body).
"""

import os

from ..soynade_api import SoynadeClient, text_in


class SoynadeTranslator:
    def __init__(self, client: SoynadeClient | None = None) -> None:
        self.client = client or SoynadeClient()
        self.temperature = float(os.environ.get("SOYNADE_MT_TEMPERATURE", "0.1"))

    def translate(self, text: str, source: str, target: str) -> str:
        if source == target or not text.strip():
            return text
        body = {"source_language": source, "target_language": target, "temperature": self.temperature, "text": text}
        response = self.client.post_json("translations", body)
        return text_in(response, ("translation", "translated_text", "text", "output"))
