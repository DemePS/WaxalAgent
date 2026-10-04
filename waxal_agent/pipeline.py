"""The whole turn: Wolof speech -> Wolof text -> English -> the agent -> English -> Wolof -> Wolof speech."""

from dataclasses import dataclass, field
from typing import Protocol

from . import audio
from .mt.base import Translator
from .stt.base import Listener
from .text import chunks, speakable
from .tts.base import Speaker

NOT_HEARD = "I did not hear anything. Please try again."  # translated like every reply: no Wolof is written by hand here


class Agent(Protocol):
    def ask(self, user_id: str, english: str) -> tuple[str, list[str]]: ...


@dataclass
class TurnResult:
    wolof: str = ""            # what was heard, in Wolof
    english: str = ""          # what the agent received
    reply_english: str = ""    # what the agent answered
    reply_wolof: str = ""      # the answer in Wolof (what is spoken)
    audio_wav: bytes = b""     # the spoken answer
    notes: list[str] = field(default_factory=list)


class Pipeline:
    def __init__(self, listener: Listener, translator: Translator, speaker: Speaker, agent: Agent) -> None:
        self.listener, self.translator, self.speaker, self.agent = listener, translator, speaker, agent

    def from_audio(self, user_id: str, recording: bytes) -> TurnResult:
        """A recording in any common format (browser webm, WhatsApp ogg...)."""
        return self.from_wolof(user_id, self.listener.transcribe(audio.to_wav(recording)))

    def transcribe(self, recording: bytes) -> str:
        """Only listen: what was said, in Wolof (no translation, no agent)."""
        return self.listener.transcribe(audio.to_wav(recording))

    def from_wolof(self, user_id: str, wolof: str) -> TurnResult:
        """Wolof text (typed, or already transcribed)."""
        result = TurnResult(wolof=wolof.strip())
        if not result.wolof:
            result.reply_english = NOT_HEARD
            result.reply_wolof = self.translator.translate(NOT_HEARD, "en", "wo")
            result.audio_wav = self.speaker.speak(result.reply_wolof)
            result.notes.append("nothing was heard")
            return result
        result.english = " ".join(self.translator.translate(s, "wo", "en") for s in chunks(result.wolof))
        result.reply_english, notes = self.agent.ask(user_id, result.english)
        result.notes += notes
        spoken = speakable(result.reply_english)
        if not spoken:
            result.notes.append("the agent gave no answer")
            return result
        parts = [self.translator.translate(s, "en", "wo") for s in chunks(spoken)]
        result.reply_wolof = " ".join(parts)
        result.audio_wav = _join_wavs([self.speaker.speak(p) for p in parts])
        return result


def _join_wavs(wavs: list[bytes]) -> bytes:
    """Concatenate WAV files of the same format (what one speaker produces) into one."""
    import io
    import wave
    if len(wavs) == 1:
        return wavs[0]
    out = io.BytesIO()
    writer = None
    for data in wavs:
        with wave.open(io.BytesIO(data)) as w:
            if writer is None:
                writer = wave.open(out, "wb")
                writer.setparams(w.getparams())
            writer.writeframes(w.readframes(w.getnframes()))
    if writer is not None:
        writer.close()
    return out.getvalue()
