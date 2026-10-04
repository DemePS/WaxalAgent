"""Listening: Wolof speech to Wolof text."""

from typing import Protocol


class Listener(Protocol):
    def transcribe(self, wav: bytes) -> str:
        """16 kHz mono WAV bytes in, the Wolof text said in it out (empty when nothing was heard)."""
        ...
