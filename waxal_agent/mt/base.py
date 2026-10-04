"""Translation between Wolof ("wo") and English ("en")."""

from typing import Protocol


class Translator(Protocol):
    def translate(self, text: str, source: str, target: str) -> str:
        """One short text (a sentence or two) from `source` to `target`, each "wo" or "en"."""
        ...
