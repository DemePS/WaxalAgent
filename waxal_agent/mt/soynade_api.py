"""Wolof <-> English translation: POST /v1/translations on Soynade's API.

Request (JSON, no model field):
    {"source_language": "wo", "target_language": "en", "temperature": 0, "text": "..."}
The answer's text is read from translation / translated_text / text / output (or a plain-text body).
"""

import logging
import os

from ..soynade_api import SoynadeClient, text_in


log = logging.getLogger("waxal.translate")


class SoynadeTranslator:
    def __init__(self, client: SoynadeClient | None = None) -> None:
        self.client = client or SoynadeClient()
        self.temperature = float(os.environ.get("SOYNADE_MT_TEMPERATURE", "0"))

    def translate(self, text: str, source: str, target: str) -> str:
        if source == target or not text.strip():
            return text
        body = {"source_language": source, "target_language": target, "temperature": self.temperature, "text": text}
        response = self.client.post_json("translations", body)
        log.debug("translations answer (%s -> %s): %s", source, target, response.text[:500])
        result = text_in(response, ("translation", "translated_text", "text", "output"))
        if result == text.strip() and len(text) > 3:
            log.warning("Soynade returned the text unchanged (%s -> %s): that pair may not be supported. Answer: %s",
                        source, target, response.text[:300])
        return result
