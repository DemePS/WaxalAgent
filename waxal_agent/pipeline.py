"""The whole turn: Wolof speech -> Wolof text -> English -> the agent -> English -> Wolof -> Wolof speech.
With WAXAL_REPLY_LANGUAGE=wo, or WAXAL_TRANSLATION=off, there is no translation at all: speech -> text -> the agent (reads and writes the
language of the person) -> speech."""

import base64
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Protocol

from . import audio
from . import language
from .language import REPLY_LANGUAGE, TRANSLATION_ON, TRANSLATION_SOURCE
from .mt.base import Translator
from .soynade_api import SoynadeError
from .stt.base import Listener
from .text import chunks, speakable
from .tts.base import Speaker, SpeechUnavailable

log = logging.getLogger("waxal.turn")
SPEECH_LIMIT = 450  # Soynade's text-to-speech refuses more than 500 characters per call
STREAM_PIECE = 200  # a streamed reply is translated in small pieces, so that the first one is spoken early
TRANSLATION_WORKERS = 4  # pieces translated at the same time
NOT_HEARD = "I did not hear anything. Please try again."  # translated like every reply: no Wolof is written by hand here
NOT_HEARD_FR = "Je n'ai rien entendu. Veuillez réessayer."  # when nothing is translated and the language is French


def _translating() -> bool:
    """Translation steps in this turn (read at each turn: the module's settings can be changed)."""
    return TRANSLATION_ON and REPLY_LANGUAGE != "wo"


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
    links: list[dict] = field(default_factory=list)  # [{"url", "label"}] the agent shared: shown and sent as text, never spoken


class Pipeline:
    def __init__(self, listener: Listener, translator: Translator, speaker: Speaker, agent: Agent) -> None:
        self.listener, self.translator, self.speaker, self.agent = listener, translator, speaker, agent
        # A listener that can turn Wolof speech straight into English (one call) does, unless WAXAL_DIRECT=off.
        # WAXAL_SHOW_WOLOF=1 also transcribes the Wolof (one more call) to show what was heard.
        # With WAXAL_REPLY_LANGUAGE=wo nothing is translated, so the Wolof text is needed: never the direct route.
        self.direct = (_translating() and hasattr(listener, "translate_audio")
                       and (os.environ.get("WAXAL_DIRECT") or "on").lower() not in ("off", "0", "no"))

    def from_audio(self, user_id: str, recording: bytes, speak: bool = True) -> TurnResult:
        """A recording in any common format (browser webm, WhatsApp ogg...). speak=False: texts only, the voice comes later
        from speak_text (a slow or failing speech service then never delays the answer)."""
        return self._answer(user_id, self.hear_audio(recording), speak)

    def hear_audio(self, recording: bytes) -> TurnResult:
        """The first half of a turn: the recording understood (recognised, and translated into English when the agent works in it)."""
        wav = audio.to_wav(recording)
        log.info("[1] heard a recording: %.1f s of audio", len(wav) / 32000)
        if not self.direct:
            return self.hear_wolof(self.listener.transcribe(wav))
        result = TurnResult()
        if os.environ.get("WAXAL_SHOW_WOLOF") in ("1", "on", "yes"):
            result.wolof = self.listener.transcribe(wav).strip()
            log.info("[2] Wolof heard: %s", result.wolof)
        started = time.monotonic()
        result.english = self.listener.translate_audio(wav).strip()
        log.info("[2] speech -> English (%.1f s): %s", time.monotonic() - started, result.english)
        return result

    def transcribe(self, recording: bytes) -> str:
        """Only listen: what was said, in Wolof (no translation, no agent)."""
        return self.listener.transcribe(audio.to_wav(recording))

    def from_wolof(self, user_id: str, wolof: str, speak: bool = True) -> TurnResult:
        """Wolof text (typed, or already transcribed)."""
        return self._answer(user_id, self.hear_wolof(wolof), speak)

    def hear_wolof(self, wolof: str) -> TurnResult:
        result = TurnResult(wolof=wolof.strip())
        log.info("[1] Wolof: %s", result.wolof)
        if result.wolof and _translating():  # without translation the agent gets what was recognised itself
            result.english = " ".join(self.translator.translate(s, "wo", "en") for s in chunks(result.wolof))
            log.info("[2] Wolof -> English: %s", result.english)
        return result

    def _ask(self, user_id: str, question: str):
        """(reply, notes, links): an agent that shares links answers with ask_full, any other with ask."""
        ask_full = getattr(self.agent, "ask_full", None)
        if ask_full:
            return ask_full(user_id, question)
        reply, notes = self.agent.ask(user_id, question)
        return reply, notes, []

    def _ask_agent(self, user_id: str, result: TurnResult) -> str:
        """Ask the agent what `result` understood. Fills the answer, the notes and the links; returns the speakable text ("" when the agent
        gave nothing to say)."""
        question = result.english if _translating() else result.wolof  # no translation: what was recognised
        log.info("[3] asking the agent: %s", question)
        started = time.monotonic()
        result.reply_english, notes, result.links = self._ask(user_id, question)
        result.notes += notes
        log.info("[3] agent answered (%.1f s): %s", time.monotonic() - started, result.reply_english)
        for note in notes:
            log.warning("[3] note: %s", note)
        spoken = speakable(result.reply_english)
        if not spoken:
            result.notes.append("the agent gave no answer")
        return spoken

    def _nothing_heard(self, result: TurnResult, speak: bool) -> None:
        """The message for a recording with nothing in it. Translated into Wolof when the turn translates; French and English are spoken as they
        are; with Wolof as the language it stays a text (no Wolof is written by hand here)."""
        result.notes.append("nothing was heard")
        if _translating():
            result.reply_english = NOT_HEARD
            result.reply_wolof = self.translator.translate(NOT_HEARD, "en", "wo")
        elif REPLY_LANGUAGE == "fr":
            result.reply_english = result.reply_wolof = NOT_HEARD_FR
        elif REPLY_LANGUAGE == "en":
            result.reply_english = result.reply_wolof = NOT_HEARD
        else:
            result.reply_english = NOT_HEARD
        if speak and result.reply_wolof:
            result.audio_wav = self._speak([result.reply_wolof], result)

    def _translate_pieces(self, pieces: list[str], pool: ThreadPoolExecutor) -> list:
        """The pieces of the answer on their way to Wolof, all at once: a list of futures, in order. A Wolof answer is not translated."""
        if not _translating() or TRANSLATION_SOURCE == "wo":
            return [_done(p) for p in pieces]
        return [pool.submit(self.translator.translate, p, TRANSLATION_SOURCE, "wo") for p in pieces]

    def _answer(self, user_id: str, result: TurnResult, speak: bool = True) -> TurnResult:
        """From what was understood: the agent's answer, in Wolof, spoken."""
        if not (result.english if _translating() else result.wolof):
            self._nothing_heard(result, speak)
            return result
        spoken = self._ask_agent(user_id, result)
        if not spoken:
            return result
        with ThreadPoolExecutor(TRANSLATION_WORKERS) as pool:  # the pieces are translated at the same time
            parts = [f.result() for f in self._translate_pieces(list(chunks(spoken)), pool)]
        result.reply_wolof = " ".join(parts)
        log.info("[4] reply -> Wolof: %s", result.reply_wolof)
        if speak:
            started = time.monotonic()
            result.audio_wav = self._speak(parts, result)
            log.info("[5] spoken (%.1f s): %d bytes of audio", time.monotonic() - started, len(result.audio_wav))
        return result

    def stream_turn(self, user_id: str, result: TurnResult):
        """The second half of a turn as a stream of events (dicts), each sent as soon as it exists:

            {"event": "heard", "wolof", "english"}      what was understood
            {"event": "answer", "reply_english", "links"}  the agent's answer (the links it shared)
            {"event": "text", "wolof"}                   a piece of the answer in Wolof, once translated
            {"event": "audio", "media", "data"}          a chunk of the voice (base64): audio/mpeg to append to one player, or a whole audio/wav clip
            {"event": "note", "text"}                    something that went wrong with the voice
            {"event": "done", "reply_wolof", "notes", "links"}   or {"event": "error", "message"}

        The answer is split into small pieces, all translated at the same time; the first piece is spoken as soon as it is translated, while
        the others still are. The voice of each piece is streamed as it is made."""
        yield {"event": "heard", "wolof": result.wolof, "english": result.english}
        pool = ThreadPoolExecutor(TRANSLATION_WORKERS)
        try:
            if not (result.english if _translating() else result.wolof):
                self._nothing_heard(result, speak=False)
                if result.reply_wolof:  # a message that can be spoken (French, English, or translated)
                    yield {"event": "text", "wolof": result.reply_wolof}
                    try:
                        for media, data in self._voice(result.reply_wolof):
                            yield {"event": "audio", "media": media, "data": base64.b64encode(data).decode("ascii")}
                    except (SpeechUnavailable, SoynadeError) as e:
                        result.notes.append(f"No voice: {e}")
                yield {"event": "done", "reply_english": result.reply_english, "reply_wolof": result.reply_wolof,
                       "notes": result.notes, "links": []}
                return
            spoken = self._ask_agent(user_id, result)
            yield {"event": "answer", "reply_english": result.reply_english, "links": result.links}
            texts: list[str] = []
            voice = bool(spoken)
            for future in self._translate_pieces(list(chunks(spoken, STREAM_PIECE)), pool):
                text = future.result()
                texts.append(text)
                yield {"event": "text", "wolof": text}
                if voice:
                    try:
                        for media, data in self._voice(text):
                            yield {"event": "audio", "media": media, "data": base64.b64encode(data).decode("ascii")}
                    except (SpeechUnavailable, SoynadeError) as e:
                        log.warning("[5] speech failed: %s", e)
                        result.notes.append(f"No voice: {e}")
                        yield {"event": "note", "text": f"No voice: {e}"}
                        voice = False  # the texts are still delivered
            result.reply_wolof = " ".join(texts)
            log.info("[4] reply -> Wolof: %s", result.reply_wolof)
            yield {"event": "done", "reply_english": result.reply_english, "reply_wolof": result.reply_wolof,
                   "notes": result.notes, "links": result.links}
        except Exception as e:  # the turn failed: the page is told, the stream ends
            log.exception("The streamed turn failed")
            yield {"event": "error", "message": f"{type(e).__name__}: {e}"[:500]}
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _voice(self, text: str):
        """(media type, bytes) chunks of the voice of a Wolof text: streamed when the speaker can, else one WAV clip per piece."""
        stream = getattr(self.speaker, "speak_stream", None)
        for piece in chunks(text, SPEECH_LIMIT):
            if stream is None:
                yield "audio/wav", self.speaker.speak(piece)
            else:
                media, body = stream(piece)
                for data in body:
                    yield media, data

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


def _done(value):
    """A future that is already finished (a piece that needs no translation)."""
    from concurrent.futures import Future
    future: Future = Future()
    future.set_result(value)
    return future


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
