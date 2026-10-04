import base64
import json

import httpx
import pytest

from tests.test_pipeline import StubAgent
from waxal_agent.mt.fake import FakeTranslator
from waxal_agent.pipeline import Pipeline
from waxal_agent.soynade_api import SoynadeClient, SoynadeError
from waxal_agent.stt.fake import FakeListener
from waxal_agent.tts import soynade_api as module
from waxal_agent.tts.base import SpeechUnavailable
from waxal_agent.tts.soynade_api import SoynadeSpeaker


@pytest.fixture(autouse=True)
def convert(monkeypatch):
    monkeypatch.setattr(module.audio, "to_wav", lambda raw: b"WAV:" + raw)


def speaker(handler, **options):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return SoynadeSpeaker(SoynadeClient("K", "https://api.example/v1", http, retries=0, min_interval=0, backoff=0), **options)


def test_text_goes_to_the_text_to_speech_route_and_audio_bytes_come_back():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "audio/wav"}, content=b"RIFF....")
    assert speaker(handler).speak("Naka nga def?") == b"WAV:RIFF...."
    assert str(seen[0].url) == "https://api.example/v1/text-to-speech"
    assert json.loads(seen[0].content) == {"model": "oolel-voices", "input": "Naka nga def?"}


def test_the_other_field_name_is_tried_when_the_first_is_rejected_and_then_remembered():
    bodies = []

    def handler(request):
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(200, content=b"RIFFaudio") if "text" in body else httpx.Response(422, json={"detail": "text required"})
    s = speaker(handler)
    assert s.speak("x") == b"WAV:RIFFaudio" and len(bodies) == 2
    s.speak("y")
    assert len(bodies) == 3 and "text" in bodies[-1]


def test_json_answers_with_base64_or_a_url_are_understood():
    encoded = base64.b64encode(b"RIFFdata").decode()
    assert speaker(lambda r: httpx.Response(200, json={"audio": encoded})).speak("x") == b"WAV:RIFFdata"

    def handler(request):
        if request.url.host == "files.example":
            return httpx.Response(200, content=b"RIFFfromurl")
        return httpx.Response(200, json={"url": "https://files.example/a.wav"})
    assert speaker(handler).speak("x") == b"WAV:RIFFfromurl"
    with pytest.raises(SoynadeError, match="no audio I recognise"):
        speaker(lambda r: httpx.Response(200, json={"hello": 1})).speak("x")


def test_a_voice_and_model_can_be_chosen(monkeypatch):
    monkeypatch.setenv("SOYNADE_TTS_MODEL", "oolel-voices-v2")
    monkeypatch.setenv("SOYNADE_TTS_VOICE", "amadou")
    seen = []
    speaker(lambda r: seen.append(json.loads(r.content)) or httpx.Response(200, content=b"RIFFx")).speak("x")
    assert seen[0] == {"model": "oolel-voices-v2", "input": "x", "voice": "amadou"}


LAUNCH = httpx.Response(400, json={"error": {"message": "Only text output is supported during launch."}})


def test_when_audio_is_not_offered_the_voice_is_unavailable_and_not_asked_again_for_a_while():
    calls = []
    s = speaker(lambda r: calls.append(1) or LAUNCH)
    with pytest.raises(SpeechUnavailable, match="does not offer speech output"):
        s.speak("x")
    first = len(calls)
    with pytest.raises(SpeechUnavailable):
        s.speak("again")
    assert len(calls) == first


def test_it_is_asked_again_after_ten_minutes(monkeypatch):
    calls = []
    s = speaker(lambda r: calls.append(1) or httpx.Response(404, json={"error": "no route"}))
    with pytest.raises(SpeechUnavailable):
        s.speak("x")
    first = len(calls)
    later = module.time.monotonic() + module.RETRY_AFTER_SECONDS + 1
    monkeypatch.setattr(module.time, "monotonic", lambda: later)
    with pytest.raises(SpeechUnavailable):
        s.speak("x")
    assert len(calls) > first


def test_it_can_be_switched_off_and_other_errors_still_surface(monkeypatch):
    with pytest.raises(SoynadeError, match="Invalid API key"):
        speaker(lambda r: httpx.Response(401, json={"error": {"message": "Invalid API key"}})).speak("x")
    monkeypatch.setenv("SOYNADE_TTS", "off")
    with pytest.raises(SpeechUnavailable, match="switched off"):
        speaker(lambda r: pytest.fail("no call expected")).speak("x")


def test_a_turn_without_voice_still_gives_the_text_answer_and_says_why():
    result = Pipeline(FakeListener(default="naka"), FakeTranslator(), speaker(lambda r: LAUNCH), StubAgent()).from_wolof("u", "jox ma total bi")
    assert result.reply_wolof.startswith("[wo]") and result.audio_wav == b""
    assert any("No voice" in n and "does not offer speech output" in n for n in result.notes)
