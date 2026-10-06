import subprocess
import sys

import pytest

from tests.test_pipeline import StubAgent
from waxal_agent import pipeline as pipeline_module
from waxal_agent.mt.fake import FakeTranslator
from waxal_agent.pipeline import Pipeline
from waxal_agent.stt.fake import FakeListener
from waxal_agent.tts.fake import FakeSpeaker


@pytest.fixture
def french(monkeypatch):
    monkeypatch.setattr(pipeline_module, "TRANSLATION_ON", False)
    monkeypatch.setattr(pipeline_module, "REPLY_LANGUAGE", "fr")
    monkeypatch.setattr(pipeline_module, "TRANSLATION_SOURCE", "fr")


class Boom(FakeTranslator):
    def translate(self, text, source, target):
        raise AssertionError("a translation was asked for")


class Direct(FakeListener):
    """A listener with the direct speech-to-English route: it must not be used."""
    def translate_audio(self, wav, source="wo", target="en"):
        raise AssertionError("the direct route was used")


def test_with_translation_off_the_turn_is_stt_agent_tts_and_nothing_is_translated(french, monkeypatch):
    monkeypatch.setattr("waxal_agent.pipeline.audio.to_wav", lambda data: b"WAV")
    agent = StubAgent(reply="Le total est 642 euros.")
    pipe = Pipeline(Direct(default="Quel est le total ?"), Boom(), FakeSpeaker(), agent)
    assert pipe.direct is False
    result = pipe.from_audio("u", b"rec")
    assert agent.asked == [("u", "Quel est le total ?")]                      # the agent gets what was recognised, in French
    assert result.reply_wolof == "Le total est 642 euros." and result.audio_wav  # and its answer is spoken as it is
    assert result.english == ""


def test_the_streamed_turn_translates_nothing_either(french):
    pipe = Pipeline(FakeListener(default="x"), Boom(), FakeSpeaker(), StubAgent(reply="Premier point. Deuxième point."))
    events = list(pipe.stream_turn("u", pipe.hear_wolof("Bonjour")))
    assert [e["event"] for e in events][0] == "heard" and events[-1]["event"] == "done"
    assert "Premier point." in events[-1]["reply_wolof"] and any(e["event"] == "audio" for e in events)


def test_nothing_heard_is_said_in_french_without_a_translation(french):
    pipe = Pipeline(FakeListener(default=""), Boom(), FakeSpeaker(), StubAgent())
    result = pipe.from_wolof("u", "  ")
    assert result.reply_wolof == pipeline_module.NOT_HEARD_FR and result.audio_wav and "nothing was heard" in result.notes


def run(code, **env):
    import os
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ, **env})
    return out.stdout.strip()


def test_the_setting_makes_french_the_default_language_and_the_prompt_says_it_is_spoken_as_written():
    code = "from waxal_agent import language, agent; print(language.REPLY_LANGUAGE, language.translating()); print(agent.SPOKEN); print('{spoken}' in agent.SYSTEM_PROMPT)"
    off = run(code, WAXAL_TRANSLATION="off", WAXAL_REPLY_LANGUAGE="")
    assert off.startswith("fr False") and "exactly as you write it, so write correct French" in off and "CAADA" not in off
    on = run(code, WAXAL_TRANSLATION="on", WAXAL_REPLY_LANGUAGE="")
    assert on.startswith("en True") and "translated into Wolof by a machine" in on
    assert run(code, WAXAL_TRANSLATION="off", WAXAL_REPLY_LANGUAGE="en").startswith("en False")        # the language can still be chosen


def test_elevenlabs_recognises_and_speaks_the_language_of_the_person_when_nothing_is_translated():
    code = ("from waxal_agent.stt.elevenlabs_api import ElevenLabsListener as L; from waxal_agent.tts.elevenlabs_api import ElevenLabsSpeaker as S; "
            "from waxal_agent.elevenlabs_api import ElevenLabsClient as C; c = C('k'); print(L(c).language, S(c).language)")
    assert run(code, WAXAL_TRANSLATION="off", WAXAL_REPLY_LANGUAGE="", ELEVENLABS_STT_LANGUAGE="x").split()[0] == "x"   # an explicit setting wins
    env = {"ELEVENLABS_API_KEY": "k"}
    import os
    base = {k: v for k, v in os.environ.items() if not k.startswith("ELEVENLABS_STT") and not k.startswith("ELEVENLABS_TTS")}
    def probe(**extra):
        return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**base, **env, **extra}).stdout.split()
    assert probe(WAXAL_TRANSLATION="off", WAXAL_REPLY_LANGUAGE="") == ["fra", "fr"]
    assert probe(WAXAL_TRANSLATION="on", WAXAL_REPLY_LANGUAGE="") == ["wol", "fr"]                      # Wolof in, French-sounding voice, as before
    assert probe(WAXAL_TRANSLATION="off", WAXAL_REPLY_LANGUAGE="en") == ["eng", "en"]


def test_whatsapp_fixed_messages_are_french_and_not_translated(french, monkeypatch):
    from waxal_agent import whatsapp
    from waxal_agent.whatsapp import FRENCH, SORRY, FILE_SAVED, WhatsAppBot
    monkeypatch.setattr(whatsapp, "REPLY_LANGUAGE", "fr")
    monkeypatch.setattr(whatsapp, "translating", lambda: False)
    sent = []

    class Client:
        def send_text(self, to, text):
            sent.append(text)
    bot = WhatsAppBot.__new__(WhatsAppBot)
    bot.pipeline, bot.client = Pipeline(FakeListener(), Boom(), FakeSpeaker(), StubAgent()), Client()
    bot._say("1", SORRY)
    bot._say("1", FILE_SAVED, name="a.pdf")
    bot._say("1", "{braces} in a refusal")
    assert sent == [FRENCH[SORRY], "J'ai ajouté le fichier à la bibliothèque : a.pdf.", "{braces} in a refusal"]


def test_the_start_up_line_says_there_is_no_translation():
    from waxal_agent.engines import describe_engines
    import os
    old = {k: os.environ.get(k) for k in ("WAXAL_TRANSLATION", "WAXAL_REPLY_LANGUAGE")}
    try:
        os.environ["WAXAL_TRANSLATION"] = "off"
        assert describe_engines("hosted")["mt"] == "none"
        os.environ["WAXAL_TRANSLATION"] = "on"
        os.environ["WAXAL_REPLY_LANGUAGE"] = "en"
        assert describe_engines("hosted")["mt"] == "claude"
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
