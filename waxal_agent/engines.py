"""The three engines of a run (listening, translating, speaking), by name. Only hosted APIs and stand-ins: no model runs here."""

from .mt.base import Translator
from .stt.base import Listener
from .tts.base import Speaker

NAMES = ("fake", "soynade-asr", "soynade", "hosted")


def _shared_soynade_client():
    """A Soynade client when any engine in use is Soynade's, else None (an ElevenLabs-only run needs no Soynade key)."""
    import os
    env = os.environ
    uses = ((env.get("WAXAL_STT") or "elevenlabs").lower() == "soynade" or (env.get("WAXAL_TTS") or "elevenlabs").lower() == "soynade"
            or (env.get("WAXAL_MT") or "claude").lower() == "soynade")
    if not uses:
        return None
    from .soynade_api import SoynadeClient
    return SoynadeClient()


def build_translator(soynade_client=None) -> Translator:
    """WAXAL_MT picks the translator: claude (default: Claude, the agent's own model) or soynade (their /translations route)."""
    import os
    choice = (os.environ.get("WAXAL_MT") or "claude").lower()
    if choice == "claude":
        from .mt.claude_api import ClaudeTranslator
        return ClaudeTranslator()
    if choice == "soynade":
        from .mt.soynade_api import SoynadeTranslator
        from .soynade_api import SoynadeClient
        return SoynadeTranslator(soynade_client or SoynadeClient())
    raise SystemExit(f"Unknown WAXAL_MT {choice!r}: use claude or soynade.")


def build_speaker(soynade_client=None) -> Speaker:
    """WAXAL_TTS picks the voice: elevenlabs (default) or soynade (their API does not offer it yet)."""
    import os
    choice = (os.environ.get("WAXAL_TTS") or "elevenlabs").lower()
    if choice == "elevenlabs":
        from .tts.elevenlabs_api import ElevenLabsSpeaker
        return ElevenLabsSpeaker()
    if choice == "soynade":
        from .soynade_api import SoynadeClient
        from .tts.soynade_api import SoynadeSpeaker
        return SoynadeSpeaker(soynade_client or SoynadeClient())
    raise SystemExit(f"Unknown WAXAL_TTS {choice!r}: use elevenlabs or soynade.")


def build_listener(soynade_client=None) -> Listener:
    """WAXAL_STT picks the recogniser: elevenlabs (default; Wolof text,
    translated to English afterwards) or soynade (Wolof speech straight to English in one call)."""
    import os
    choice = (os.environ.get("WAXAL_STT") or "elevenlabs").lower()
    if choice == "elevenlabs":
        from .stt.elevenlabs_api import ElevenLabsListener
        return ElevenLabsListener()
    if choice == "soynade":
        from .soynade_api import SoynadeClient
        from .stt.soynade_api import SoynadeListener
        return SoynadeListener(soynade_client or SoynadeClient())
    raise SystemExit(f"Unknown WAXAL_STT {choice!r}: use soynade or elevenlabs.")


def describe_engines(name: str) -> dict[str, str]:
    """What each stage really uses for this run, as the start-up messages report it: {"stt": ..., "mt": ..., "tts": ...}."""
    import os
    if name == "fake":
        return {"stt": "stand-in", "mt": "stand-in", "tts": "stand-in"}
    env = os.environ
    off = (env.get("WAXAL_TRANSLATION") or "on").strip().lower() in ("off", "0", "no", "false") or env.get("WAXAL_REPLY_LANGUAGE") == "wo"
    mt = "none" if off else (env.get("WAXAL_MT") or "claude").lower()  # no translation at all
    if name == "soynade-asr":
        return {"stt": "soynade", "mt": "stand-in", "tts": "stand-in"}
    return {"stt": (env.get("WAXAL_STT") or "elevenlabs").lower(), "mt": mt, "tts": (env.get("WAXAL_TTS") or "elevenlabs").lower()}


def build_engines(name: str) -> tuple[Listener, Translator, Speaker]:
    """fake: stand-ins for everything (no key needed).
    soynade-asr: Soynade's hosted speech recognition (SOYNADE_API_KEY); translation and voice are stand-ins.
    soynade: recognition and speech through Soynade's API, translation by Claude (WAXAL_MT=soynade: Soynade's route too)."""
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
    if name in ("soynade", "hosted"):  # recognition and voice by WAXAL_STT / WAXAL_TTS (default Soynade), translation by WAXAL_MT
        client = _shared_soynade_client()  # one client (one rate limit, one cooldown) for every Soynade route in use
        return build_listener(client), build_translator(client), build_speaker(client)
    raise SystemExit(f"Unknown engines {name!r}: use one of {', '.join(NAMES)}.")
