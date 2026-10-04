import base64
import json

import httpx
import pytest

from waxal_agent.soynade_api import SoynadeClient, SoynadeError
from waxal_agent.stt.soynade_api import PROMPT, SoynadeListener


def client(handler, **options):
    return SoynadeClient("KEY", "https://api.example/v1", httpx.Client(transport=httpx.MockTransport(handler)),
                         backoff=0, **options)


def answer(text):
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": text}}]})


def test_transcription_sends_the_audio_as_the_quickstart_shows():
    seen = []

    def handler(request):
        seen.append(request)
        return answer("  nanga def  ")
    text = SoynadeListener(client(handler)).transcribe(b"RIFFwavbytes")
    request = seen[0]
    body = json.loads(request.content)
    assert text == "nanga def"
    assert str(request.url) == "https://api.example/v1/chat/completions" and request.headers["authorization"] == "Bearer KEY"
    assert body["model"] == "oolel-speech-v1" and body["modalities"] == ["text"] and body["temperature"] == 0
    audio, instruction = body["messages"][0]["content"]
    assert audio == {"type": "input_audio", "input_audio": {"data": base64.b64encode(b"RIFFwavbytes").decode(), "format": "wav"}}
    assert instruction == {"type": "text", "text": PROMPT}


def test_rate_limits_and_server_errors_are_retried_then_succeed():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, json={"error": {"message": "slow down"}}) if len(calls) < 3 else answer("ok")
    assert SoynadeListener(client(handler)).transcribe(b"x") == "ok" and len(calls) == 3


def test_a_refusal_is_not_retried_and_the_error_says_why():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, json={"error": {"message": "Invalid API key"}})
    with pytest.raises(SoynadeError, match="HTTP 401: Invalid API key"):
        SoynadeListener(client(handler)).transcribe(b"x")
    assert len(calls) == 1


def test_giving_up_after_the_retries_and_network_errors():
    def down(request):
        raise httpx.ConnectError("no route")
    with pytest.raises(SoynadeError, match="network error"):
        SoynadeListener(client(down, retries=1)).transcribe(b"x")


def test_an_odd_answer_is_reported_and_the_key_is_required(monkeypatch):
    with pytest.raises(SoynadeError, match="Unexpected answer"):
        SoynadeListener(client(lambda r: httpx.Response(200, json={"oops": 1}))).transcribe(b"x")
    monkeypatch.delenv("SOYNADE_API_KEY", raising=False)
    with pytest.raises(SoynadeError, match="SOYNADE_API_KEY"):
        SoynadeClient()


def test_model_and_base_url_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("SOYNADE_ASR_MODEL", "oolel-speech-v2")
    monkeypatch.setenv("SOYNADE_BASE_URL", "https://other.example/v1/")
    seen = []
    http = httpx.Client(transport=httpx.MockTransport(lambda r: seen.append(r) or answer("x")))
    SoynadeListener(SoynadeClient("K", http=http)).transcribe(b"x")
    assert json.loads(seen[0].content)["model"] == "oolel-speech-v2" and str(seen[0].url).startswith("https://other.example/v1/chat")
