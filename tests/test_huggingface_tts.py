import json

import httpx
import pytest

from waxal_agent.tts import huggingface_api
from waxal_agent.tts.base import SpeechUnavailable
from waxal_agent.tts.huggingface_api import HuggingFaceSpeaker


@pytest.fixture(autouse=True)
def convert(monkeypatch):
    monkeypatch.setattr(huggingface_api.audio, "to_wav", lambda raw: b"WAV:" + raw)


def speaker(handler, **options):
    return HuggingFaceSpeaker("TOKEN", http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None, **options)


def test_the_text_is_posted_to_the_router_and_the_audio_converted():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=b"FLAC-BYTES")
    assert speaker(handler).speak("Naka nga def?") == b"WAV:FLAC-BYTES"
    request = seen[0]
    assert str(request.url) == "https://router.huggingface.co/hf-inference/models/facebook/mms-tts-wol"
    assert request.headers["authorization"] == "Bearer TOKEN" and json.loads(request.content) == {"inputs": "Naka nga def?"}


def test_a_loading_model_is_waited_for_then_used():
    calls, waited = [], []

    def handler(request):
        calls.append(1)
        return httpx.Response(503, json={"error": "loading", "estimated_time": 12.5}) if len(calls) == 1 else httpx.Response(200, content=b"A")
    s = HuggingFaceSpeaker("T", http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=waited.append)
    assert s.speak("x") == b"WAV:A" and waited == [12.5]


def test_a_model_that_is_not_served_says_so_and_is_not_fatal_to_the_turn():
    with pytest.raises(SpeechUnavailable, match="cannot run facebook/mms-tts-wol.*serverless"):
        speaker(lambda r: httpx.Response(404, json={"error": "Model not found"})).speak("x")
    with pytest.raises(SpeechUnavailable, match="refused the token"):
        speaker(lambda r: httpx.Response(401, json={"error": "Invalid token"})).speak("x")
    with pytest.raises(SpeechUnavailable, match="rate limit"):
        speaker(lambda r: httpx.Response(429, json={"error": "slow down"})).speak("x")


def test_a_token_is_required(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    with pytest.raises(SpeechUnavailable, match="HF_TOKEN"):
        HuggingFaceSpeaker().speak("x")


def test_model_and_payload_key_can_be_changed(monkeypatch):
    monkeypatch.setenv("WAXAL_TTS_MODEL", "me/wolof-tts")
    monkeypatch.setenv("WAXAL_TTS_KEY", "text_inputs")
    seen = []
    speaker(lambda r: seen.append(r) or httpx.Response(200, content=b"A")).speak("x")
    assert str(seen[0].url).endswith("/models/me/wolof-tts") and json.loads(seen[0].content) == {"text_inputs": "x"}


def test_waxal_tts_chooses_the_voice(monkeypatch):
    from waxal_agent.engines import build_speaker
    monkeypatch.setenv("SOYNADE_API_KEY", "k")
    monkeypatch.setenv("WAXAL_TTS", "huggingface")
    assert type(build_speaker()).__name__ == "HuggingFaceSpeaker"
    monkeypatch.setenv("WAXAL_TTS", "soynade")
    assert type(build_speaker()).__name__ == "SoynadeSpeaker"
    monkeypatch.setenv("WAXAL_TTS", "nope")
    with pytest.raises(SystemExit, match="Unknown WAXAL_TTS"):
        build_speaker()
