import io
import wave

from waxal_agent.mt.fake import FakeTranslator
from waxal_agent.pipeline import Pipeline
from waxal_agent.stt.fake import FakeListener
from waxal_agent.tts.fake import FakeSpeaker


class StubAgent:
    def __init__(self, reply="Total is 642 euros. The invoice is paid.", notes=()):
        self.reply, self.notes, self.asked = reply, list(notes), []

    def ask(self, user_id, english):
        self.asked.append((user_id, english))
        return self.reply, self.notes


def make(listener=None, translator=None, agent=None):
    return Pipeline(listener or FakeListener(default="wolof words"), translator or FakeTranslator(),
                    FakeSpeaker(), agent or StubAgent())


def seconds(wav: bytes) -> float:
    with wave.open(io.BytesIO(wav)) as w:
        return w.getnframes() / w.getframerate()


def test_a_wolof_text_goes_to_english_then_back():
    table = {("jox ma total bi.", "wo", "en"): "give me the total."}
    agent = StubAgent()
    pipeline = make(translator=FakeTranslator(table), agent=agent)
    result = pipeline.from_wolof("alice", "jox ma total bi.")
    assert agent.asked == [("alice", "give me the total.")]
    assert result.wolof == "jox ma total bi." and result.english == "give me the total."
    assert result.reply_wolof == "[wo] Total is 642 euros. The invoice is paid."   # one translation call, not one per sentence
    assert seconds(result.audio_wav) > 0.5 and result.notes == []


def test_only_speakable_text_is_translated_and_spoken():
    agent = StubAgent("The total is 642.\n```\nsecret code\n```\n| a | b |")
    translator, pipeline_speaker = FakeTranslator(), FakeSpeaker()
    pipeline = Pipeline(FakeListener(default="x"), translator, pipeline_speaker, agent)
    result = pipeline.from_wolof("u", "naka")
    assert result.reply_english.startswith("The total")           # the written reply is kept whole
    assert pipeline_speaker.spoken == ["[wo] The total is 642."]  # but only plain sentences are spoken


def test_silence_is_answered_without_calling_the_agent():
    agent = StubAgent()
    result = make(agent=agent).from_wolof("u", "   ")
    assert agent.asked == [] and result.notes == ["nothing was heard"] and result.audio_wav


def test_notes_from_the_agent_are_passed_on():
    result = make(agent=StubAgent(notes=["Claude is unreachable"])).from_wolof("u", "naka")
    assert "Claude is unreachable" in result.notes


def test_a_recording_is_converted_then_listened_to(monkeypatch):
    from waxal_agent import audio, pipeline as module
    monkeypatch.setattr(module.audio, "to_wav", lambda data: b"WAV" + data)
    listener = FakeListener("nanga def")
    result = Pipeline(listener, FakeTranslator(), FakeSpeaker(), StubAgent()).from_audio("u", b"abc")
    assert listener.heard == [6] and result.wolof == "nanga def"
