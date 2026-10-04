import httpx
import pytest

from tests.test_pipeline import StubAgent
from waxal_agent.mt.fake import FakeTranslator
from waxal_agent.pipeline import Pipeline
from waxal_agent.soynade_api import SoynadeClient
from waxal_agent.stt.fake import FakeListener
from waxal_agent.tts import soynade_api as tts_module
from waxal_agent.tts.base import SpeechUnavailable
from waxal_agent.tts.soynade_api import SoynadeSpeaker


def speaker(handler):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return SoynadeSpeaker(SoynadeClient("K", "https://api.example/v1", http, backoff=0, min_interval=0, retries=0), model="oolel-speech-v1")


LAUNCH = httpx.Response(400, json={"error": {"message": "Only text output is supported during launch."}})


def test_the_launch_message_means_no_voice_and_is_not_asked_again_for_a_while():
    calls = []

    def handler(request):
        calls.append(1)
        return LAUNCH
    s = speaker(handler)
    with pytest.raises(SpeechUnavailable, match="does not offer speech output yet"):
        s.speak("Naka nga def?")
    first = len(calls)
    with pytest.raises(SpeechUnavailable):
        s.speak("again")
    assert len(calls) == first                                   # no new call while the answer is known


def test_it_is_asked_again_after_ten_minutes(monkeypatch):
    calls = []
    s = speaker(lambda request: calls.append(1) or LAUNCH)
    with pytest.raises(SpeechUnavailable):
        s.speak("x")
    first = len(calls)
    later = tts_module.time.monotonic() + tts_module.RETRY_AFTER_SECONDS + 1
    monkeypatch.setattr(tts_module.time, "monotonic", lambda: later)
    with pytest.raises(SpeechUnavailable):
        s.speak("x")
    assert len(calls) > first


def test_it_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("SOYNADE_TTS", "off")
    with pytest.raises(SpeechUnavailable, match="switched off"):
        speaker(lambda request: pytest.fail("no call expected")).speak("x")


def test_other_errors_still_surface():
    from waxal_agent.soynade_api import SoynadeError
    with pytest.raises(SoynadeError, match="Invalid API key"):
        speaker(lambda request: httpx.Response(401, json={"error": {"message": "Invalid API key"}})).speak("x")


def test_a_turn_without_voice_still_gives_the_text_answer_and_says_why():
    s = speaker(lambda request: LAUNCH)
    result = Pipeline(FakeListener(default="naka"), FakeTranslator(), s, StubAgent()).from_wolof("u", "jox ma total bi")
    assert result.reply_wolof.startswith("[wo]") and result.audio_wav == b""
    assert any("No voice" in n and "does not offer speech output yet" in n for n in result.notes)
