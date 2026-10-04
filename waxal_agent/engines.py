"""The three engines of a run (listening, translating, speaking), by name. Only hosted APIs and stand-ins: no model runs here."""

from .mt.base import Translator
from .stt.base import Listener
from .tts.base import Speaker

NAMES = ("fake", "soynade-asr", "soynade")


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
    """WAXAL_TTS picks the voice: soynade (default: their API does not offer it yet), oolel-demo (Oolel-Voices through
    Soynade's public demo Space), or huggingface (MMS Wolof, HF_TOKEN)."""
    import os
    choice = (os.environ.get("WAXAL_TTS") or "soynade").lower()
    if choice == "huggingface":
        from .tts.huggingface_api import HuggingFaceSpeaker
        return HuggingFaceSpeaker()
    if choice in ("oolel-demo", "oolel-voices"):
        from .tts.gradio_space import GradioSpeaker
        return GradioSpeaker()
    if choice == "soynade":
        from .soynade_api import SoynadeClient
        from .tts.soynade_api import SoynadeSpeaker
        return SoynadeSpeaker(soynade_client or SoynadeClient())
    raise SystemExit(f"Unknown WAXAL_TTS {choice!r}: use soynade, huggingface or oolel-demo.")


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
    if name == "soynade":  # everything through Soynade's API (one client, one key)
        from .soynade_api import SoynadeClient
        from .stt.soynade_api import SoynadeListener
        client = SoynadeClient()
        return SoynadeListener(client), build_translator(client), build_speaker(client)
    raise SystemExit(f"Unknown engines {name!r}: use one of {', '.join(NAMES)}.")
