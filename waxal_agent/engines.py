"""The three engines of a run (listening, translating, speaking), by name. Only hosted APIs and stand-ins: no model runs here."""

from .mt.base import Translator
from .settings import Settings
from .stt.base import Listener
from .tts.base import Speaker

NAMES = ("fake", "soynade-asr", "soynade", "hosted")


def _shared_soynade_client(settings: Settings):
    """A Soynade client when any engine in use is Soynade's, else None (an ElevenLabs-only run needs no Soynade key)."""
    if settings.stt != "soynade" and settings.tts != "soynade" and settings.mt != "soynade":
        return None
    from .soynade_api import SoynadeClient
    return SoynadeClient()


def build_translator(settings: Settings, soynade_client=None) -> Translator:
    """settings.mt picks the translator: claude (default: Claude, the agent's own model) or soynade (their /translations route)."""
    if settings.mt == "claude":
        from .mt.claude_api import ClaudeTranslator
        return ClaudeTranslator()
    if settings.mt == "soynade":
        from .mt.soynade_api import SoynadeTranslator
        from .soynade_api import SoynadeClient
        return SoynadeTranslator(soynade_client or SoynadeClient())
    raise SystemExit(f"Unknown WAXAL_MT {settings.mt!r}: use claude or soynade.")


def build_speaker(settings: Settings, soynade_client=None) -> Speaker:
    """settings.tts picks the voice: elevenlabs (default), soynade, huggingface or oolel-demo."""
    if settings.tts == "elevenlabs":
        from .tts.elevenlabs_api import ElevenLabsSpeaker
        return ElevenLabsSpeaker(language=settings.language)
    if settings.tts == "soynade":
        from .soynade_api import SoynadeClient
        from .tts.soynade_api import SoynadeSpeaker
        return SoynadeSpeaker(soynade_client or SoynadeClient())
    if settings.tts == "huggingface":
        from .tts.huggingface_api import HuggingFaceSpeaker
        return HuggingFaceSpeaker()
    if settings.tts == "oolel-demo":
        from .tts.gradio_space import GradioSpeaker
        return GradioSpeaker()
    raise SystemExit(f"Unknown WAXAL_TTS {settings.tts!r}: use elevenlabs, soynade, huggingface or oolel-demo.")


def build_listener(settings: Settings, soynade_client=None) -> Listener:
    """settings.stt picks the recogniser: elevenlabs (default; Wolof text,
    translated to English afterwards) or soynade (Wolof speech straight to English in one call)."""
    if settings.stt == "elevenlabs":
        from .stt.elevenlabs_api import ElevenLabsListener
        return ElevenLabsListener(language=settings.language)
    if settings.stt == "soynade":
        from .soynade_api import SoynadeClient
        from .stt.soynade_api import SoynadeListener
        return SoynadeListener(soynade_client or SoynadeClient())
    raise SystemExit(f"Unknown WAXAL_STT {settings.stt!r}: use soynade or elevenlabs.")


def describe_engines(name: str, settings: Settings | None = None) -> dict[str, str]:
    """What each stage really uses for this run, as the start-up messages report it: {"stt": ..., "mt": ..., "tts": ...}."""
    if name == "fake":
        return {"stt": "stand-in", "mt": "stand-in", "tts": "stand-in"}
    settings = settings or Settings()
    mt = "none" if not settings.language.translating else settings.mt  # no translation at all
    if name == "soynade-asr":
        return {"stt": "soynade", "mt": "stand-in", "tts": "stand-in"}
    return {"stt": settings.stt, "mt": mt, "tts": settings.tts}


def build_engines(name: str, settings: Settings | None = None) -> tuple[Listener, Translator, Speaker]:
    """fake: stand-ins for everything (no key needed).
    soynade-asr: Soynade's hosted speech recognition (SOYNADE_API_KEY); translation and voice are stand-ins.
    hosted/soynade: recognition and voice by settings.stt / settings.tts (default elevenlabs), translation by settings.mt."""
    if name == "fake":
        from .mt.fake import FakeTranslator
        from .stt.fake import FakeListener
        from .tts.fake import FakeSpeaker
        return FakeListener(default="Nanga def?"), FakeTranslator(), FakeSpeaker()
    if name == "soynade-asr":
        from .mt.fake import FakeTranslator
        from .stt.soynade_api import SoynadeListener
        from .tts.fake import FakeSpeaker
        return SoynadeListener(), FakeTranslator(), FakeSpeaker()
    if name in ("soynade", "hosted"):
        settings = settings or Settings()
        client = _shared_soynade_client(settings)  # one client (one rate limit, one cooldown) for every Soynade route in use
        return build_listener(settings, client), build_translator(settings, client), build_speaker(settings, client)
    raise SystemExit(f"Unknown engines {name!r}: use one of {', '.join(NAMES)}.")
