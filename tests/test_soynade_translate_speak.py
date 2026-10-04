import base64
import json

import httpx
import pytest

from tests.test_server import tone
from waxal_agent.mt.soynade_api import SoynadeTranslator
from waxal_agent.soynade_api import SoynadeClient, SoynadeError
from waxal_agent.tts.soynade_api import SoynadeSpeaker


def client(handler):
    return SoynadeClient("KEY", "https://api.example/v1", httpx.Client(transport=httpx.MockTransport(handler)), backoff=0, min_interval=0, retries=0)


def chat_answer(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


MODELS = {"data": [{"id": "oolel-speech-v1"}, {"id": "oolel-v1"}, {"id": "oolel-voices-v1"}]}


def test_the_model_list_is_read_from_the_api():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=MODELS)
    assert client(handler).models() == ["oolel-speech-v1", "oolel-v1", "oolel-voices-v1"]
    assert seen[0].method == "GET" and str(seen[0].url) == "https://api.example/v1/models"


def test_translation_asks_with_the_direction_prompt_and_finds_its_model():
    bodies = []

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS)
        bodies.append(json.loads(request.content))
        return chat_answer("  Nanga def  ")
    mt = SoynadeTranslator(client(handler))
    assert mt.translate("How are you?", "en", "wo") == "Nanga def"
    assert bodies[0]["model"] == "oolel-v1"                      # not the speech or the voice model
    assert bodies[0]["messages"][0] == {"role": "system", "content": "Translate to Wolof the following sentence"}
    mt.translate("naka nga def", "wo", "en")
    assert bodies[1]["messages"][0]["content"] == "Translate to English the following sentence"
    assert mt.translate("  ", "en", "wo") == "  " and mt.translate("x", "wo", "wo") == "x"


def test_an_unclear_model_list_asks_you_to_set_the_variable_and_shows_the_list():
    def handler(request):
        return httpx.Response(200, json={"data": [{"id": "alpha"}, {"id": "beta"}]})
    with pytest.raises(SoynadeError, match="SOYNADE_MT_MODEL.*alpha, beta|alpha, beta.*SOYNADE_MT_MODEL"):
        SoynadeTranslator(client(handler)).translate("Hi", "en", "wo")


def test_speech_uses_the_audio_speech_route_first(monkeypatch):
    seen = []

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS)
        seen.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, content=tone())
    monkeypatch.setattr("waxal_agent.tts.soynade_api.audio.to_wav", lambda raw: b"WAV:" + raw[:4])
    speaker = SoynadeSpeaker(client(handler), voice="amy")
    assert speaker.speak("Nanga def") == b"WAV:RIFF"
    path, body = seen[0]
    assert path.endswith("/audio/speech") and body == {"model": "oolel-voices-v1", "input": "Nanga def", "voice": "amy",
                                                      "response_format": "wav"}


def test_speech_falls_back_to_chat_audio_when_the_route_does_not_exist(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/audio/speech"):
            return httpx.Response(404, json={"error": {"message": "not found"}})
        body = json.loads(request.content)
        assert body["modalities"] == ["text", "audio"] and body["audio"] == {"voice": "default", "format": "wav"}
        return httpx.Response(200, json={"choices": [{"message": {"audio": {"data": base64.b64encode(b"AUDIO").decode()}}}]})
    monkeypatch.setattr("waxal_agent.tts.soynade_api.audio.to_wav", lambda raw: b"WAV:" + raw)
    assert SoynadeSpeaker(client(handler), model="oolel-voices-v1").speak("x") == b"WAV:AUDIO"
    assert calls == ["/v1/audio/speech", "/v1/chat/completions"]


def test_other_speech_errors_are_not_hidden_by_the_fallback():
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "Invalid API key"}})
    with pytest.raises(SoynadeError, match="Invalid API key"):
        SoynadeSpeaker(client(handler), model="m").speak("x")


def test_a_chat_answer_without_audio_is_reported(monkeypatch):
    monkeypatch.setenv("SOYNADE_TTS_ROUTE", "chat")
    with pytest.raises(SoynadeError, match="no audio"):
        SoynadeSpeaker(client(lambda r: chat_answer("text only")), model="m").speak("x")


def test_the_full_soynade_engine_set_shares_one_client(monkeypatch):
    from waxal_agent.engines import build_engines
    monkeypatch.setenv("SOYNADE_API_KEY", "k")
    listener, translator, speaker = build_engines("soynade")
    assert listener.client is translator.client is speaker.client


def test_a_key_with_a_single_model_uses_it_for_translation_and_speech(monkeypatch):
    calls = []

    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "oolel-speech-v1"}]})
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if "audio" in body.get("modalities", []):
            return httpx.Response(200, json={"choices": [{"message": {"audio": {"data": base64.b64encode(b"A").decode()}}}]})
        return chat_answer("Nanga def")
    c = client(handler)
    assert SoynadeTranslator(c).translate("How are you?", "en", "wo") == "Nanga def"
    monkeypatch.setattr("waxal_agent.tts.soynade_api.audio.to_wav", lambda raw: b"WAV:" + raw)
    assert SoynadeSpeaker(c).speak("Nanga def") == b"WAV:A"
    assert all(body["model"] == "oolel-speech-v1" for path, body in calls)
    assert calls[1][0].endswith("/chat/completions")           # a speech chat model is asked on the chat route first
