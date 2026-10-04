"""The three engines of a run (listening, translating, speaking), by name. Only hosted APIs and stand-ins: no model runs here."""

from .mt.base import Translator
from .stt.base import Listener
from .tts.base import Speaker

NAMES = ("fake", "soynade-asr", "soynade")


def build_engines(name: str) -> tuple[Listener, Translator, Speaker]:
    """fake: stand-ins for everything (no key needed).
    soynade-asr: Soynade's hosted speech recognition (SOYNADE_API_KEY); translation and voice are stand-ins.
    soynade: everything through Soynade's API: recognition, translation and speech output (the last two are my best reading
    of an OpenAI-compatible API, not confirmed by Soynade's reference: scripts/check_api.py shows what works)."""
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
        from .mt.soynade_api import SoynadeTranslator
        from .soynade_api import SoynadeClient
        from .stt.soynade_api import SoynadeListener
        from .tts.soynade_api import SoynadeSpeaker
        client = SoynadeClient()
        return SoynadeListener(client), SoynadeTranslator(client), SoynadeSpeaker(client)
    raise SystemExit(f"Unknown engines {name!r}: use one of {', '.join(NAMES)}.")
