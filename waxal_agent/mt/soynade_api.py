"""Wolof <-> English translation through Soynade's hosted API (a chat model asked to translate).

The system prompt "Translate to Wolof the following sentence" is the one Soynade's own translation pipeline uses; the
opposite direction is its mirror (unverified: SOYNADE_MT_PROMPT_WO_EN / SOYNADE_MT_PROMPT_EN_WO change them).
The model is SOYNADE_MT_MODEL, else the one found in the model list (see `scripts/check_api.py models`).
"""

import os

from ..soynade_api import SoynadeClient
from ..soynade_models import pick

PROMPTS = {"en-wo": "Translate to Wolof the following sentence", "wo-en": "Translate to English the following sentence"}


class SoynadeTranslator:
    def __init__(self, client: SoynadeClient | None = None, model: str | None = None) -> None:
        self.client = client or SoynadeClient()
        self._model = model or os.environ.get("SOYNADE_MT_MODEL")
        self.prompts = {"en-wo": os.environ.get("SOYNADE_MT_PROMPT_EN_WO") or PROMPTS["en-wo"],
                        "wo-en": os.environ.get("SOYNADE_MT_PROMPT_WO_EN") or PROMPTS["wo-en"]}

    @property
    def model(self) -> str:
        if self._model is None:
            self._model = pick(self.client, "translation", "SOYNADE_MT_MODEL")
        return self._model

    def translate(self, text: str, source: str, target: str) -> str:
        if source == target or not text.strip():
            return text
        completion = self.client.chat(
            self.model,
            [{"role": "system", "content": self.prompts[f"{source}-{target}"]}, {"role": "user", "content": text}],
            temperature=0, max_tokens=512)
        return self.client.text_of(completion)
