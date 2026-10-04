"""Speaking: Wolof text to speech."""

from typing import Protocol


class SpeechUnavailable(Exception):
    """No speech can be produced right now (the service does not offer it yet, or it is switched off): the reply is
    given as text only."""


class Speaker(Protocol):
    def speak(self, text: str) -> bytes:
        """Wolof text in, WAV bytes out."""
        ...
