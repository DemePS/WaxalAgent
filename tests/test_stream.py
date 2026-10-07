import base64
import json
import threading

import pytest
from fastapi.testclient import TestClient

from tests.test_pipeline import StubAgent
from waxal_agent import pipeline as pipeline_module
from waxal_agent.mt.fake import FakeTranslator
from waxal_agent.pipeline import Pipeline, TurnResult
from waxal_agent.server import create_app
from waxal_agent.stt.fake import FakeListener
from waxal_agent.tts.base import SpeechUnavailable
from waxal_agent.tts.fake import FakeSpeaker

THREE = " ".join(f"Sentence number {i} says something that is long enough to fill a piece of its own, {'x' * 100}." for i in (1, 2, 3))


@pytest.fixture(autouse=True)
def english(monkeypatch):
    monkeypatch.setattr(pipeline_module, "REPLY_LANGUAGE", "en")
    monkeypatch.setattr(pipeline_module, "TRANSLATION_SOURCE", "en")


class Streaming(FakeSpeaker):
    def speak_stream(self, text):
        return "audio/mpeg", iter([b"AA", text.encode()[:4]])


def make(translator=None, speaker=None, agent=None):
    return Pipeline(FakeListener(default="naka"), translator or FakeTranslator(), speaker or Streaming(), agent or StubAgent(reply=THREE))


def understood(pipe, wolof="jox ma total bi"):
    return pipe.hear_wolof(wolof)


def test_the_events_come_in_order_and_the_pieces_are_translated_and_spoken():
    pipe = make()
    events = list(pipe.stream_turn("u", understood(pipe)))
    kinds = [e["event"] for e in events]
    assert kinds[:2] == ["heard", "answer"] and kinds[-1] == "done"
    assert kinds.count("text") == 3 and kinds.count("audio") == 9                 # three pieces, each: two chunks of voice and an empty one that ends the audio file
    first_text = kinds.index("text")
    assert kinds[first_text:first_text + 4] == ["text", "audio", "audio", "audio"]  # a piece is spoken right after its text
    assert [e["data"] for e in events[first_text + 1:first_text + 4] if e["event"] == "audio"][-1] == ""      # and its file ends with an empty chunk
    assert events[0]["wolof"] == "jox ma total bi" and events[0]["english"].startswith("[en]")
    assert events[1]["reply_english"] == THREE
    assert events[-1]["reply_wolof"] == " ".join(e["wolof"] for e in events if e["event"] == "text")
    assert base64.b64decode(next(e for e in events if e["event"] == "audio")["data"]) == b"AA"


def test_the_pieces_are_translated_at_the_same_time():
    barrier = threading.Barrier(3, timeout=5)           # passes only when the three translations run together

    class Together(FakeTranslator):
        def translate(self, text, source, target):
            barrier.wait()
            return super().translate(text, source, target)
    pipe = make()
    heard = understood(pipe, "naka")         # the question is translated one by one: only the answer is translated together
    pipe.translator = Together()
    events = list(pipe.stream_turn("u", heard))
    assert [e["event"] for e in events].count("text") == 3 and events[-1]["event"] == "done"


def test_the_first_piece_is_spoken_before_the_last_one_is_translated():
    gate = threading.Event()

    class Slow(FakeTranslator):
        def translate(self, text, source, target):
            if "number 3" in text:
                assert gate.wait(5), "the last piece was translated before anything was spoken: no streaming"
            return super().translate(text, source, target)
    pipe = make()
    heard = understood(pipe, "naka")
    pipe.translator = Slow()
    seen = []
    for event in pipe.stream_turn("u", heard):
        seen.append(event["event"])
        if event["event"] == "audio":
            gate.set()
    assert seen.count("text") == 3 and seen[-1] == "done"


def test_a_speaker_that_cannot_stream_sends_one_wav_clip_per_piece():
    pipe = make(speaker=FakeSpeaker())
    audio = [e for e in pipe.stream_turn("u", understood(pipe)) if e["event"] == "audio"]
    assert len(audio) == 3 and all(e["media"] == "audio/wav" and base64.b64decode(e["data"])[:4] == b"RIFF" for e in audio)


def test_in_wolof_mode_nothing_is_translated_but_the_voice_still_streams(monkeypatch):
    monkeypatch.setattr(pipeline_module, "REPLY_LANGUAGE", "wo")
    monkeypatch.setattr(pipeline_module, "TRANSLATION_SOURCE", "wo")
    translator = FakeTranslator()
    pipe = make(translator, agent=StubAgent(reply="Total bi mooy 642. Jërëjëf."))
    events = list(pipe.stream_turn("u", pipe.hear_wolof("naka")))
    assert translator.calls == [] and [e for e in events if e["event"] == "text"][0]["wolof"].startswith("Total bi")
    assert any(e["event"] == "audio" for e in events)


def test_nothing_heard_ends_the_stream_without_asking_the_agent():
    agent = StubAgent()
    pipe = make(agent=agent)
    events = list(pipe.stream_turn("u", pipe.hear_wolof("  ")))
    assert [e["event"] for e in events][:2] == ["heard", "text"] and events[-1]["event"] == "done" and agent.asked == []
    assert events[-1]["reply_english"] == pipeline_module.NOT_HEARD and "nothing was heard" in events[-1]["notes"]
    assert events[1]["wolof"].startswith("[wo]")                                  # the message is translated and spoken like any reply


def test_a_failing_voice_is_a_note_and_the_texts_still_come():
    class Off(FakeSpeaker):
        def speak_stream(self, text):
            raise SpeechUnavailable("switched off")
    pipe = make(speaker=Off())
    events = list(pipe.stream_turn("u", understood(pipe)))
    kinds = [e["event"] for e in events]
    assert kinds.count("text") == 3 and "audio" not in kinds and kinds.count("note") == 1 and kinds[-1] == "done"
    assert "switched off" in events[-1]["notes"][0]


def test_a_failing_agent_ends_the_stream_with_an_error_event():
    class Broken(StubAgent):
        def ask(self, user_id, question):
            raise RuntimeError("no Claude access")
    pipe = make(agent=Broken())
    events = list(pipe.stream_turn("u", understood(pipe)))
    assert [e["event"] for e in events] == ["heard", "error"] and "no Claude access" in events[-1]["message"]


def lines(response):
    return [json.loads(line) for line in response.text.splitlines() if line]


def test_the_server_streams_json_lines():
    client = TestClient(create_app(make()))
    r = client.post("/api/text/stream", json={"text": "jox ma total bi"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    events = lines(r)
    assert events[0]["event"] == "heard" and events[-1]["event"] == "done" and any(e["event"] == "audio" for e in events)


def test_the_stream_routes_refuse_what_the_others_refuse():
    secret = TestClient(create_app(make(), "secret"))
    assert secret.post("/api/text/stream", json={"text": "x"}).status_code == 403
    assert secret.post("/api/turn/stream", content=b"x").status_code == 403
    assert TestClient(create_app(make())).post("/api/turn/stream", content=b"").status_code == 400
