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


def speaker(handler):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return SoynadeSpeaker(SoynadeClient("K", "https://api.example/v1", http, retries=0, min_interval=0, backoff=0))


def test_the_request_is_the_one_in_soynades_reference_and_the_wav_comes_back():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "audio/wav"}, content=b"RIFF....")
    assert speaker(handler).speak("Naka nga def?") == b"WAV:RIFF...."
    assert str(seen[0].url) == "https://api.example/v1/text-to-speech" and seen[0].headers["authorization"] == "Bearer K"
    assert json.loads(seen[0].content) == {"text": "Naka nga def?", "language": "wo", "output_format": "wav"}


def test_the_tuning_values_can_be_changed(monkeypatch):
    monkeypatch.setenv("SOYNADE_TTS_EXAGGERATION", "0.5")
    monkeypatch.setenv("SOYNADE_TTS_TEMPERATURE", "0.3")
    monkeypatch.setenv("SOYNADE_TTS_CFG", "0.7")
    monkeypatch.setenv("SOYNADE_TTS_SEED", "42")
    body = speaker(lambda r: httpx.Response(200, content=b"RIFFx")).request_body("x")
    assert (body["exaggeration"], body["temperature"], body["cfg_weight"], body["seed"]) == (0.5, 0.3, 0.7, 42)


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
