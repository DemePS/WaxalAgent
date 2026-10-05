import json

import httpx
import pytest

from waxal_agent import http_calls
from waxal_agent.mt.soynade_api import SoynadeTranslator
from waxal_agent.soynade_api import SoynadeClient, SoynadeError, text_in
from waxal_agent.stt.soynade_api import SoynadeListener
from waxal_agent.text import chunks


def make(handler, **options):
    options.setdefault("min_interval", 0)
    options.setdefault("backoff", 0)
    return SoynadeClient("KEY", "https://api.example/v1", httpx.Client(transport=httpx.MockTransport(handler)), **options)


@pytest.fixture
def sleeps(monkeypatch):
    waited = []
    monkeypatch.setattr(http_calls.time, "sleep", waited.append)
    return waited


# --- recognition: POST /audio/transcriptions, multipart

def test_transcription_is_a_multipart_upload_to_its_own_route():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"text": "  nanga def  "})
    assert SoynadeListener(make(handler)).transcribe(b"RIFFwav") == "nanga def"
    request = seen[0]
    assert str(request.url) == "https://api.example/v1/audio/transcriptions" and request.headers["authorization"] == "Bearer KEY"
    assert request.headers["content-type"].startswith("multipart/form-data")
    assert b'name="model"' in request.content and b"oolel-speech-v1" in request.content and b"RIFFwav" in request.content
    assert b'name="file"' in request.content and b"audio.wav" in request.content


def test_a_language_can_be_sent(monkeypatch):
    monkeypatch.setenv("SOYNADE_ASR_LANGUAGE", "wo")
    seen = []
    SoynadeListener(make(lambda r: seen.append(r) or httpx.Response(200, json={"text": "x"}))).transcribe(b"x")
    assert b'name="language"' in seen[0].content


# --- speech translation: POST /audio/translations, as in Soynade's reference

def test_speech_goes_straight_to_english_in_one_call():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"text": " How are you? "})
    assert SoynadeListener(make(handler)).translate_audio(b"RIFFwav") == "How are you?"
    request = seen[0]
    assert str(request.url) == "https://api.example/v1/audio/translations" and request.headers["content-type"].startswith("multipart/form-data")
    for field in (b'name="source_language"', b"wo", b'name="target_language"', b"en", b'name="response_format"', b"json",
                  b'name="temperature"', b"0", b'name="file"', b"RIFFwav"):
        assert field in request.content


# --- translation: POST /translations, JSON, no model field

def test_translation_sends_soynades_documented_body():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"translation": " Naka nga def? "})
    assert SoynadeTranslator(make(handler)).translate("How are you?", "en", "wo") == "Naka nga def?"
    assert bodies == [{"source_language": "en", "target_language": "wo", "temperature": 0.0, "text": "How are you?"}]


def test_a_rejected_request_shows_soynades_detail():
    with pytest.raises(SoynadeError, match="field required"):
        SoynadeTranslator(make(lambda r: httpx.Response(422, json={"detail": "field required"}))).translate("x", "en", "wo")


def test_other_errors_are_not_hidden_and_empty_or_same_language_text_is_skipped():
    with pytest.raises(SoynadeError, match="HTTP 401: Invalid API key"):
        SoynadeTranslator(make(lambda r: httpx.Response(401, json={"error": {"message": "Invalid API key"}}))).translate("x", "en", "wo")
    mt = SoynadeTranslator(make(lambda r: pytest.fail("no call expected")))
    assert mt.translate("  ", "en", "wo") == "  " and mt.translate("a", "wo", "wo") == "a"


def test_answers_are_read_in_several_shapes():
    assert text_in(httpx.Response(200, json={"data": {"translated_text": "A"}}), ("translation", "translated_text")) == "A"
    assert text_in(httpx.Response(200, text="plain"), ("text",)) == "plain"
    with pytest.raises(SoynadeError, match="Unexpected answer"):
        text_in(httpx.Response(200, json={"oops": 1}), ("text",))


# --- the client: rate limits and errors

def test_a_429_waits_as_the_server_says_then_succeeds(sleeps):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "7"}, json={"title": "Too Many Requests"}) if len(calls) == 1 \
            else httpx.Response(200, json={"text": "ok"})
    assert SoynadeListener(make(handler)).transcribe(b"x") == "ok" and 7 in sleeps


def test_without_retry_after_the_wait_grows_and_a_final_429_explains_itself(sleeps):
    with pytest.raises(SoynadeError) as raised:
        SoynadeListener(make(lambda r: httpx.Response(429, json={"title": "Too Many"}), retries=3, backoff=2)).transcribe(b"x")
    assert sleeps == [2, 4, 8] and "rate limit of your Soynade plan" in str(raised.value) and raised.value.status == 429


def test_calls_are_spaced_by_the_minimum_interval(monkeypatch):
    now = [100.0]
    waited = []
    monkeypatch.setattr(http_calls.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(http_calls.time, "sleep", lambda s: (waited.append(s), now.__setitem__(0, now[0] + s)))
    listener = SoynadeListener(make(lambda r: httpx.Response(200, json={"text": "x"}), min_interval=0.5))
    listener.transcribe(b"x")
    listener.transcribe(b"x")
    assert waited and abs(waited[0] - 0.5) < 1e-6


def test_network_errors_a_missing_key_and_the_environment(monkeypatch):
    def down(request):
        raise httpx.ConnectError("no route")
    with pytest.raises(SoynadeError, match="network error"):
        SoynadeListener(make(down, retries=1)).transcribe(b"x")
    monkeypatch.delenv("SOYNADE_API_KEY", raising=False)
    with pytest.raises(SoynadeError, match="SOYNADE_API_KEY"):
        SoynadeClient()
    monkeypatch.setenv("SOYNADE_API_KEY", "k")
    monkeypatch.setenv("SOYNADE_RETRIES", "1")
    monkeypatch.setenv("SOYNADE_BASE_URL", "https://other.example/v1/")
    c = SoynadeClient()
    assert c.retries == 1 and c.base_url == "https://other.example/v1"


def test_sentences_are_packed_into_as_few_pieces_as_possible():
    text = "One two three. Four five six. Seven eight nine. Ten eleven twelve."
    assert chunks(text, 600) == [text]
    pieces = chunks(text, 32)
    assert all(len(p) <= 32 for p in pieces) and " ".join(pieces) == text and len(pieces) == 3 and chunks("", 100) == []


def test_a_failing_server_is_tried_twice_not_for_minutes():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(502, text="<html><title>502: Bad gateway</title></html>")
    with pytest.raises(SoynadeError, match="502: Bad gateway"):
        make(handler).post_json("text-to-speech", {"text": "x"})
    assert len(calls) == 2


def test_after_a_rate_limit_that_retries_did_not_clear_no_call_is_made_for_a_while(sleeps):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, json={"title": "Too Many Requests"})
    client = make(handler, retries=1)
    with pytest.raises(SoynadeError, match="rate limit of your Soynade plan"):
        client.post_json("translations", {"text": "x"})
    assert len(calls) == 2
    with pytest.raises(SoynadeError, match="not calling again") as raised:         # refused at once, without a call
        client.post_json("translations", {"text": "y"})
    assert len(calls) == 2 and raised.value.status == 429
