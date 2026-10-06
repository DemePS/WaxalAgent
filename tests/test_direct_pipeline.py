import pytest

from tests.test_pipeline import StubAgent
from waxal_agent.mt.fake import FakeTranslator
from waxal_agent.pipeline import Pipeline
from waxal_agent.stt.fake import FakeListener
from waxal_agent.tts.fake import FakeSpeaker


class DirectListener(FakeListener):
    """A listener that can also turn Wolof speech straight into English."""

    def __init__(self, english="give me the total", wolof="jox ma total bi"):
        super().__init__(wolof)
        self.english, self.direct_calls = english, 0

    def translate_audio(self, wav, source="wo", target="en"):
        self.direct_calls += 1
        return self.english


@pytest.fixture(autouse=True)
def no_ffmpeg(monkeypatch):
    monkeypatch.setattr("waxal_agent.pipeline.audio.to_wav", lambda data: b"WAV")
    monkeypatch.delenv("WAXAL_DIRECT", raising=False)
    monkeypatch.delenv("WAXAL_SHOW_WOLOF", raising=False)


def make(listener, agent=None):
    return Pipeline(listener, FakeTranslator(), FakeSpeaker(), agent or StubAgent())


def test_a_voice_note_is_understood_in_one_call_without_translating_the_incoming_side():
    listener, agent = DirectListener(), StubAgent()
    translator = FakeTranslator()
    result = Pipeline(listener, translator, FakeSpeaker(), agent).from_audio("u", b"rec")
    assert agent.asked == [("u", "give me the total")] and listener.direct_calls == 1
    assert listener.heard == []                                        # no separate recognition call
    assert all(call[1:] == ("en", "wo") for call in translator.calls)  # only the reply is translated (en -> wo)
    assert result.english == "give me the total" and result.wolof == "" and result.audio_wav


def test_the_wolof_can_be_shown_at_the_price_of_one_more_call(monkeypatch):
    monkeypatch.setenv("WAXAL_SHOW_WOLOF", "1")
    listener = DirectListener()
    result = make(listener).from_audio("u", b"rec")
    assert result.wolof == "jox ma total bi" and listener.heard == [3]


def test_direct_mode_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("WAXAL_DIRECT", "off")
    listener, agent = DirectListener(), StubAgent()
    Pipeline(listener, FakeTranslator(), FakeSpeaker(), agent).from_audio("u", b"rec")
    assert listener.direct_calls == 0 and agent.asked == [("u", "[en] jox ma total bi")]


def test_silence_in_direct_mode_is_answered_without_the_agent():
    agent = StubAgent()
    result = make(DirectListener(english="  "), agent).from_audio("u", b"rec")
    assert agent.asked == [] and result.notes == ["nothing was heard"]


def test_a_listener_without_the_direct_route_keeps_the_two_step_path():
    agent = StubAgent()
    result = make(FakeListener("naka"), agent).from_audio("u", b"rec")
    assert agent.asked == [("u", "[en] naka")] and result.wolof == "naka"


def test_the_reply_language_is_the_source_of_the_translation_to_wolof(monkeypatch):
    from waxal_agent import pipeline
    monkeypatch.setattr(pipeline, "TRANSLATION_SOURCE", "pt")
    translator = FakeTranslator()
    p = pipeline.Pipeline.__new__(pipeline.Pipeline)
    p.translator, p.speaker = translator, FakeSpeaker()
    p.agent = type("A", (), {"ask": lambda self, u, e: ("Le total est 642.", [])})()
    p._answer("u", pipeline.TurnResult(english="total?"))
    assert translator.calls[-1] == ("Le total est 642.", "pt", "wo")


def test_a_wolof_reply_is_spoken_without_translation(monkeypatch):
    monkeypatch.setattr("waxal_agent.pipeline.TRANSLATION_SOURCE", "wo")
    translator = FakeTranslator()
    result = Pipeline(DirectListener(), translator, FakeSpeaker(), StubAgent()).from_audio("u", b"rec")
    assert translator.calls == [] and result.reply_wolof and result.audio_wav        # WAXAL_REPLY_LANGUAGE=wo (the default)


# --- WAXAL_REPLY_LANGUAGE=wo: no translation at all ---------------------------------------------------------------------

def test_in_wolof_mode_the_agent_gets_the_wolof_and_its_answer_is_spoken_without_any_translation(monkeypatch):
    monkeypatch.setattr("waxal_agent.pipeline.REPLY_LANGUAGE", "wo")
    monkeypatch.setattr("waxal_agent.pipeline.TRANSLATION_SOURCE", "wo")
    translator, agent, listener = FakeTranslator(), StubAgent(reply="Total bi mooy 642."), DirectListener()
    pipeline = Pipeline(listener, translator, FakeSpeaker(), agent)
    assert pipeline.direct is False                                   # the direct Wolof-to-English route is never used
    result = pipeline.from_audio("u", b"rec")
    assert translator.calls == [] and listener.direct_calls == 0      # nothing translated, in either direction
    assert agent.asked == [("u", "jox ma total bi")]                  # the agent got the Wolof as recognised
    assert result.reply_wolof == "Total bi mooy 642." and result.audio_wav and result.english == ""


def test_in_wolof_mode_nothing_heard_is_a_text_note_only(monkeypatch):
    monkeypatch.setattr("waxal_agent.pipeline.REPLY_LANGUAGE", "wo")
    translator = FakeTranslator()
    result = Pipeline(FakeListener(default=""), translator, FakeSpeaker(), StubAgent()).from_wolof("u", "  ")
    assert translator.calls == [] and result.reply_english and not result.reply_wolof and not result.audio_wav
    assert "nothing was heard" in result.notes


def test_in_the_other_languages_the_question_is_still_translated(monkeypatch):
    monkeypatch.setattr("waxal_agent.pipeline.REPLY_LANGUAGE", "en")
    translator, agent = FakeTranslator(), StubAgent()
    Pipeline(FakeListener(default="naka"), translator, FakeSpeaker(), agent).from_wolof("u", "jox ma total bi")
    assert translator.calls[0][1:] == ("wo", "en") and agent.asked[0][1].startswith("[en]")
