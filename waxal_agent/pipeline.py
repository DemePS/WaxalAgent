"""The whole turn: Wolof speech -> Wolof text -> English -> the agent -> English -> Wolof -> Wolof speech.
With WAXAL_REPLY_LANGUAGE=wo there is no translation at all: Wolof text -> the agent (reads and writes Wolof) -> Wolof speech."""

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Protocol

from . import audio
from .language import REPLY_LANGUAGE, TRANSLATION_SOURCE
from .mt.base import Translator
from .soynade_api import SoynadeError
from .stt.base import Listener
from .text import chunks, speakable
from .tts.base import Speaker, SpeechUnavailable

log = logging.getLogger("waxal.turn")
SPEECH_LIMIT = 450  # Soynade's text-to-speech refuses more than 500 characters per call
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
        # A listener that can turn Wolof speech straight into English (one call) does, unless WAXAL_DIRECT=off.
        # WAXAL_SHOW_WOLOF=1 also transcribes the Wolof (one more call) to show what was heard.
        # With WAXAL_REPLY_LANGUAGE=wo nothing is translated, so the Wolof text is needed: never the direct route.
        self.direct = (REPLY_LANGUAGE != "wo" and hasattr(listener, "translate_audio")
                       and (os.environ.get("WAXAL_DIRECT") or "on").lower() not in ("off", "0", "no"))

    def from_audio(self, user_id: str, recording: bytes, speak: bool = True) -> TurnResult:
        """A recording in any common format (browser webm, WhatsApp ogg...). speak=False: texts only, the voice comes later
        from speak_text (a slow or failing speech service then never delays the answer)."""
        wav = audio.to_wav(recording)
        log.info("[1] heard a recording: %.1f s of audio", len(wav) / 32000)
        if not self.direct:
            return self.from_wolof(user_id, self.listener.transcribe(wav), speak)
        result = TurnResult()
        if os.environ.get("WAXAL_SHOW_WOLOF") in ("1", "on", "yes"):
            result.wolof = self.listener.transcribe(wav).strip()
            log.info("[2] Wolof heard: %s", result.wolof)
        started = time.monotonic()
        result.english = self.listener.translate_audio(wav).strip()
        log.info("[2] speech -> English (%.1f s): %s", time.monotonic() - started, result.english)
        return self._answer(user_id, result, speak)

    def transcribe(self, recording: bytes) -> str:
        """Only listen: what was said, in Wolof (no translation, no agent)."""
        return self.listener.transcribe(audio.to_wav(recording))

    def from_wolof(self, user_id: str, wolof: str, speak: bool = True) -> TurnResult:
        """Wolof text (typed, or already transcribed)."""
        result = TurnResult(wolof=wolof.strip())
        log.info("[1] Wolof: %s", result.wolof)
        if result.wolof and REPLY_LANGUAGE != "wo":  # in Wolof mode the agent gets the Wolof itself
            result.english = " ".join(self.translator.translate(s, "wo", "en") for s in chunks(result.wolof))
            log.info("[2] Wolof -> English: %s", result.english)
        return self._answer(user_id, result, speak)

    def _answer(self, user_id: str, result: TurnResult, speak: bool = True) -> TurnResult:
        """From the English the agent received: the agent's answer, in Wolof, spoken."""
        question = result.wolof if REPLY_LANGUAGE == "wo" else result.english  # Wolof mode: no translation
        if not question:
            result.reply_english = NOT_HEARD
            result.notes.append("nothing was heard")
            if REPLY_LANGUAGE != "wo":  # in Wolof mode no Wolof is written by hand: the message stays text
                result.reply_wolof = self.translator.translate(NOT_HEARD, "en", "wo")
                if speak:
                    result.audio_wav = self._speak([result.reply_wolof], result)
            return result
        log.info("[3] asking the agent: %s", question)
        started = time.monotonic()
        result.reply_english, notes = self.agent.ask(user_id, question)
        result.notes += notes
        log.info("[3] agent answered (%.1f s): %s", time.monotonic() - started, result.reply_english)
        for note in notes:
            log.warning("[3] note: %s", note)
        spoken = speakable(result.reply_english)
        if not spoken:
            result.notes.append("the agent gave no answer")
            return result
        parts = list(chunks(spoken)) if TRANSLATION_SOURCE == "wo" else [  # a Wolof reply is spoken as it is
            self.translator.translate(s, TRANSLATION_SOURCE, "wo") for s in chunks(spoken)]
        result.reply_wolof = " ".join(parts)
        log.info("[4] reply -> Wolof: %s", result.reply_wolof)
        if speak:
            started = time.monotonic()
            result.audio_wav = self._speak(parts, result)
            log.info("[5] spoken (%.1f s): %d bytes of audio", time.monotonic() - started, len(result.audio_wav))
        return result

    def stop(self) -> bool:
        """Ask the agent to stop its running turn; False when it has none."""
        stop = getattr(self.agent, "stop", None)
        return bool(stop and stop())

    def speak_text(self, wolof: str) -> tuple[bytes, list[str]]:
        """The voice of a Wolof text, on its own (after the texts were delivered): (WAV, notes; empty WAV when it failed)."""
        result = TurnResult()
        started = time.monotonic()
        wav = self._speak([wolof], result)
        log.info("[5] spoken (%.1f s): %d bytes of audio", time.monotonic() - started, len(wav))
        return wav, result.notes

    def speak_stream(self, wolof: str):
        """(media type, an iterator of audio bytes, notes): the voice of a Wolof text as it is made, one piece (at most SPEECH_LIMIT
        characters) after the other. A speaker that cannot stream gives each piece whole, as WAV. No voice: ("", empty, notes)."""
        pieces = chunks(wolof, SPEECH_LIMIT)
        stream = getattr(self.speaker, "speak_stream", None)
        try:
            if not pieces:
                return "", iter(()), []
            if stream is None:
                return "audio/wav", iter([_join_wavs([self.speaker.speak(c) for c in pieces])]), []
            media, first = stream(pieces[0])

            def body():
                yield from first
                for c in pieces[1:]:
                    yield from stream(c)[1]
            return media, body(), []
        except (SpeechUnavailable, SoynadeError) as e:
            log.warning("[5] speech failed: %s", e)
            return "", iter(()), [f"No voice: {e}"]

    def _speak(self, parts: list[str], result: TurnResult) -> bytes:
        """The spoken reply; when speech output is not available, the reply stays text only (and says why in the notes)."""
        try:
            pieces = [c for p in parts for c in chunks(p, SPEECH_LIMIT)]  # the speech route takes at most 500 characters
            return _join_wavs([self.speaker.speak(c) for c in pieces])
        except SpeechUnavailable as e:
            result.notes.append(f"No voice: {e}")
            return b""
        except SoynadeError as e:  # e.g. Soynade's gateway is down (502): the texts are still delivered
            log.warning("[5] speech failed: %s", e)
            result.notes.append(f"No voice: {e}")
            return b""


def _join_wavs(wavs: list[bytes]) -> bytes:
    """Concatenate WAV files of the same format (what one speaker produces) into one."""
    import io
    import wave
    out = io.BytesIO()
    writer = None
    for data in wavs:
        with wave.open(io.BytesIO(data)) as w:
            if writer is None:
                writer = wave.open(out, "wb")
                writer.setparams(w.getparams()._replace(nframes=0))  # a streamed WAV states a bogus length (0xFFFFFFFF)
            writer.writeframes(w.readframes(w.getnframes()))
    if writer is not None:
        writer.close()
    return out.getvalue()
