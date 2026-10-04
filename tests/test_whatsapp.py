import hashlib
import hmac
import json
import shutil

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.test_pipeline import StubAgent
from tests.test_server import tone
from waxal_agent import whatsapp
from waxal_agent.mt.fake import FakeTranslator
from waxal_agent.pipeline import Pipeline
from waxal_agent.server import create_app
from waxal_agent.stt.fake import FakeListener
from waxal_agent.tts.fake import FakeSpeaker
from waxal_agent.whatsapp import WhatsAppBot, WhatsAppClient, WhatsAppConfig, messages_in, signature_ok

SECRET = "app-secret"
CONFIG = WhatsAppConfig("TOKEN", "PHONE_ID", "verify-me", SECRET, {"221771234567"})


def payload(*messages) -> dict:
    return {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [
        {"field": "messages", "value": {"messaging_product": "whatsapp", "messages": list(messages)}}]}]}


def audio_message(id="wamid.1", sender="221771234567", media="MEDIA1"):
    return {"from": sender, "id": id, "type": "audio", "audio": {"id": media, "mime_type": "audio/ogg; codecs=opus", "voice": True}}


def text_message(body="naka", id="wamid.2", sender="221771234567"):
    return {"from": sender, "id": id, "type": "text", "text": {"body": body}}


class Meta:
    """A stand-in for Meta's servers: records what we send, serves one voice note."""

    def __init__(self, recording: bytes = b"OGG-BYTES"):
        self.recording, self.sent, self.uploads, self.requests = recording, [], [], []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["authorization"] == "Bearer TOKEN"
        path = request.url.path
        if request.method == "GET" and path.endswith("/MEDIA1"):
            return httpx.Response(200, json={"url": "https://media.example/dl/1"})
        if request.method == "GET" and request.url.host == "media.example":
            return httpx.Response(200, content=self.recording)
        if path.endswith("/PHONE_ID/media"):
            self.uploads.append(request.content)
            return httpx.Response(200, json={"id": "UPLOADED1"})
        if path.endswith("/PHONE_ID/messages"):
            self.sent.append(json.loads(request.content))
            return httpx.Response(200, json={"messages": [{"id": "wamid.out"}]})
        return httpx.Response(404)


def make_bot(meta=None, listener=None, translator=None, agent=None):
    meta = meta or Meta()
    pipeline = Pipeline(listener or FakeListener(default="jox ma total bi"), translator or FakeTranslator(),
                        FakeSpeaker(), agent or StubAgent())
    client = WhatsAppClient(CONFIG, httpx.Client(transport=httpx.MockTransport(meta)))
    return WhatsAppBot(pipeline, client, CONFIG), meta


@pytest.fixture
def wav_as_ogg(monkeypatch):
    """No ffmpeg needed for these tests: the conversions are replaced by labels."""
    monkeypatch.setattr(whatsapp.audio, "to_wav", lambda data: b"WAV:" + data)
    monkeypatch.setattr(whatsapp.audio, "to_ogg_opus", lambda wav: b"OGG:" + wav[:4])


def test_signature_is_checked_with_the_app_secret():
    body = b'{"a":1}'
    good = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert signature_ok(body, good, SECRET)
    assert not signature_ok(body, good, "other-secret") and not signature_ok(b"{}", good, SECRET)
    assert not signature_ok(body, None, SECRET) and not signature_ok(body, "md5=abc", SECRET)


def test_verification_handshake():
    bot, _ = make_bot()
    ok = {"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "12345"}
    assert bot.verify(ok) == "12345"
    assert bot.verify({**ok, "hub.verify_token": "wrong"}) is None
    assert bot.verify({**ok, "hub.mode": "unsubscribe"}) is None


def test_only_messages_are_picked_out_of_a_call():
    status = {"entry": [{"changes": [{"field": "messages", "value": {"statuses": [{"id": "x", "status": "read"}]}}]}]}
    other = {"entry": [{"changes": [{"field": "account_update", "value": {}}]}]}
    assert messages_in(status) == [] and messages_in(other) == []
    assert messages_in(payload(audio_message(), text_message())) == [audio_message(), text_message()]


def test_a_voice_note_gets_a_voice_note_and_a_text_back(wav_as_ogg):
    listener = FakeListener("jox ma total bi")
    bot, meta = make_bot(listener=listener)
    bot.handle(payload(audio_message()))
    assert listener.heard == [len(b"WAV:OGG-BYTES")]                    # the downloaded recording was what was heard
    kinds = [m["type"] for m in meta.sent]
    assert kinds == ["text", "audio"] and meta.sent[1]["audio"] == {"id": "UPLOADED1"}   # the text first, then the voice
    assert meta.sent[0]["to"] == "221771234567" and meta.sent[0]["text"]["body"].startswith("[wo]")
    assert len(meta.uploads) == 1 and b"OGG:" in meta.uploads[0]


def test_a_typed_message_is_answered_too(wav_as_ogg):
    bot, meta = make_bot()
    bot.handle(payload(text_message("jox ma total bi")))
    assert [m["type"] for m in meta.sent] == ["text", "audio"]


def test_the_same_message_delivered_twice_is_answered_once(wav_as_ogg):
    bot, meta = make_bot()
    bot.handle(payload(text_message(id="wamid.same")))
    bot.handle(payload(text_message(id="wamid.same")))
    assert [m["type"] for m in meta.sent] == ["text", "audio"]


def test_a_number_that_is_not_allowed_gets_no_answer(wav_as_ogg):
    agent = StubAgent()
    bot, meta = make_bot(agent=agent)
    bot.handle(payload(text_message(sender="221700000000")))
    assert meta.sent == [] and agent.asked == []


def test_other_kinds_of_message_get_a_short_explanation(wav_as_ogg):
    bot, meta = make_bot()
    bot.handle(payload({"from": "221771234567", "id": "wamid.img", "type": "image", "image": {"id": "I1"}}))
    assert [m["type"] for m in meta.sent] == ["text"] and "voice notes" in meta.sent[0]["text"]["body"]


def test_a_failing_turn_says_sorry_and_the_next_message_still_works(wav_as_ogg):
    class Broken(StubAgent):
        def ask(self, user_id, english):
            raise RuntimeError("model down")
    bot, meta = make_bot(agent=Broken())
    bot.handle(payload(text_message(id="a"), text_message(id="b")))
    assert [m["type"] for m in meta.sent] == ["text", "text"] and "went wrong" in meta.sent[0]["text"]["body"]


def test_config_from_the_environment():
    env = {"WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "p", "WHATSAPP_VERIFY_TOKEN": "v",
           "WHATSAPP_APP_SECRET": "s", "WAXAL_ALLOWED": "+221 77 123 45 67, 33612345678,"}
    config = WhatsAppConfig.from_env(env)
    assert config.allowed == {"221771234567", "33612345678"} and config.graph_version == "v21.0"
    with pytest.raises(SystemExit, match="WHATSAPP_APP_SECRET"):
        WhatsAppConfig.from_env({k: v for k, v in env.items() if k != "WHATSAPP_APP_SECRET"})
    assert WhatsAppConfig.from_env({**env, "WAXAL_ALLOWED": ""}).allowed == set()  # empty: nobody


# --- the web routes

def web(bot, **options):
    return TestClient(create_app(bot.pipeline, bot=bot, **options))


def signed(body: dict) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    return raw, {"x-hub-signature-256": "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest(),
                 "content-type": "application/json"}


def test_webhook_handshake_over_http():
    bot, _ = make_bot()
    c = web(bot)
    r = c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "777"})
    assert r.status_code == 200 and r.text == "777"
    assert c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "no", "hub.challenge": "1"}).status_code == 403


def test_webhook_refuses_a_bad_signature_and_accepts_a_good_one(wav_as_ogg):
    bot, meta = make_bot()
    c = web(bot)
    raw, headers = signed(payload(text_message()))
    assert c.post("/webhook", content=raw, headers={**headers, "x-hub-signature-256": "sha256=00"}).status_code == 403
    assert c.post("/webhook", content=raw).status_code == 403 and meta.sent == []
    assert c.post("/webhook", content=raw, headers=headers).status_code == 200
    assert [m["type"] for m in meta.sent] == ["text", "audio"]        # the background task ran


def test_a_public_server_can_leave_out_the_test_page():
    bot, _ = make_bot()
    c = web(bot, test_page=False)
    assert c.get("/").status_code == 404 and c.post("/api/text", json={"text": "x"}).status_code in (404, 405)
    assert c.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "1"}).status_code == 200


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_the_real_conversions_work_end_to_end():
    bot, meta = make_bot(meta=Meta(recording=tone()))
    bot.handle(payload(audio_message()))
    assert [m["type"] for m in meta.sent] == ["text", "audio"] and meta.uploads[0][:0] == b""
    assert b"OggS" in meta.uploads[0]
