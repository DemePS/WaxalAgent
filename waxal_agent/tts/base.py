"""Speaking: Wolof text to speech."""

from typing import Protocol


class Speaker(Protocol):
    def speak(self, text: str) -> bytes:
        """Wolof text in, WAV bytes out."""
        ...
