"""The three speech/translation engines of a real run, by name."""

from .mt.base import Translator
from .stt.base import Listener
from .tts.base import Speaker

NAMES = ("fake", "soynade", "wolof")


def build_engines(name: str) -> tuple[Listener, Translator, Speaker]:
    """fake: stand-ins. soynade: Soynade Research's Wolof-HuBERT-CTC, Oolel and Oolel-Voices.
    wolof: the first set: a Whisper Wolof model, NLLB-200 and SpeechT5."""
    if name == "fake":
        from .mt.fake import FakeTranslator
        from .stt.fake import FakeListener
        from .tts.fake import FakeSpeaker
        return FakeListener(default="Nanga def?"), FakeTranslator(), FakeSpeaker()
    if name == "soynade":
        from .mt.oolel import Oolel
        from .stt.whisper_wolof import SOYNADE_MODEL, WhisperWolof
        from .tts.oolel_voices import OolelVoices
        import os
        return WhisperWolof(os.environ.get("WAXAL_ASR_MODEL") or SOYNADE_MODEL), Oolel(), OolelVoices()
    if name == "wolof":
        from .mt.nllb import Nllb
        from .stt.whisper_wolof import WhisperWolof
        from .tts.speecht5_wolof import SpeechT5Wolof
        return WhisperWolof(), Nllb(), SpeechT5Wolof()
    raise SystemExit(f"Unknown engines {name!r}: use one of {', '.join(NAMES)}.")
