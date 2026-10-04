import base64
import io
import shutil
import wave

import pytest
from fastapi.testclient import TestClient

from waxal_agent import audio
from waxal_agent.mt.fake import FakeTranslator
from waxal_agent.pipeline import Pipeline
from waxal_agent.server import create_app
from waxal_agent.stt.fake import FakeListener
from waxal_agent.tts.fake import FakeSpeaker
from tests.test_pipeline import StubAgent


def client(token=None, listener=None):
    pipeline = Pipeline(listener or FakeListener(default="naka"), FakeTranslator(), FakeSpeaker(), StubAgent())
    return TestClient(create_app(pipeline, token))


def tone() -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
        w.writeframes(b"\x00\x10" * 8000)
    return out.getvalue()


def test_the_page_is_served():
    r = client().get("/")
    assert r.status_code == 200 and "Hold to talk" in r.text


def test_text_turn_returns_both_languages_and_audio():
    r = client().post("/api/text", json={"text": "jox ma total bi"}, headers={"x-user": "alice"})
    data = r.json()
    assert r.status_code == 200 and data["wolof"] == "jox ma total bi" and data["english"].startswith("[en]")
    assert data["reply_wolof"] and base64.b64decode(data["audio"])[:4] == b"RIFF"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_audio_turn_converts_the_recording():
    r = client(listener=FakeListener("nanga def")).post("/api/turn", content=tone(), headers={"content-type": "audio/wav"})
    assert r.status_code == 200 and r.json()["wolof"] == "nanga def"


def test_bad_audio_and_empty_bodies_are_refused():
    c = client()
    assert c.post("/api/turn", content=b"").status_code == 400
    if shutil.which("ffmpeg"):
        assert c.post("/api/turn", content=b"not audio at all").status_code == 400


def test_token_is_required_when_set():
    c = client(token="s3cret")
    assert c.post("/api/text", json={"text": "x"}).status_code == 403
    assert c.post("/api/text", json={"text": "x"}, headers={"x-token": "wrong"}).status_code == 403
    assert c.post("/api/text", json={"text": "x"}, headers={"x-token": "s3cret"}).status_code == 200


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_wav_to_ogg_opus_and_back():
    ogg = audio.to_ogg_opus(tone())
    assert ogg[:4] == b"OggS" and audio.to_wav(ogg)[:4] == b"RIFF"


def test_transcribe_only_returns_just_the_wolof_words(monkeypatch):
    from waxal_agent.soynade_api import SoynadeError
    c = client(listener=FakeListener("nanga def"))
    monkeypatch.setattr("waxal_agent.pipeline.audio.to_wav", lambda data: b"WAV")
    r = c.post("/api/transcribe", content=b"recording")
    assert r.status_code == 200 and r.json() == {"wolof": "nanga def"}
    assert c.post("/api/transcribe", content=b"").status_code == 400

    class Down:
        def transcribe(self, wav):
            raise SoynadeError("Soynade API call failed (oolel-speech-v1): HTTP 401: Invalid API key")
    down = client(listener=Down())
    r = down.post("/api/transcribe", content=b"recording")
    assert r.status_code == 502 and "Invalid API key" in r.json()["detail"]


def test_the_page_offers_a_transcribe_only_switch():
    assert 'id="only"' in client().get("/").text


def test_the_page_gets_the_texts_first_and_the_voice_afterwards():
    c = client()
    first = c.post("/api/text?speak=0", json={"text": "naka nga def"}).json()
    assert first["reply_wolof"] and first["audio"] == ""
    voice = c.post("/api/speak", json={"text": first["reply_wolof"]}).json()
    assert voice["audio"] and voice["notes"] == []


def test_the_stop_button_reaches_the_agent():
    c = client()
    assert c.post("/api/stop").json() == {"stopped": False}     # the stand-in agent has no turn to stop
