import io
import json
import wave

import httpx
import pytest

from waxal_agent.elevenlabs_api import ElevenLabsClient, ElevenLabsError
from waxal_agent.engines import build_engines
from waxal_agent.pipeline import Pipeline
from waxal_agent.stt.elevenlabs_api import ElevenLabsListener
from waxal_agent.tts.elevenlabs_api import ElevenLabsSpeaker


def client(handler, **options):
    return ElevenLabsClient("KEY", "https://eleven.example", httpx.Client(transport=httpx.MockTransport(handler)), **options)


def test_speech_is_posted_to_the_voice_and_raw_pcm_becomes_a_wav():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=b"\x01\x00" * 160)
    wav = ElevenLabsSpeaker(client(handler)).speak("Nanga def?")
    request = seen[0]
    assert request.url.path == "/v1/text-to-speech/JBFqnCBsd6RMkjVDRZzb" and request.url.params["output_format"] == "pcm_16000"
    assert request.headers["xi-api-key"] == "KEY" and json.loads(request.content) == {"text": "Nanga def?", "model_id": "eleven_v4", "language_code": "fr"}
    with wave.open(io.BytesIO(wav)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 16000, 160)


def test_voice_model_and_language_can_be_changed(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "V2")
    monkeypatch.setenv("ELEVENLABS_TTS_MODEL", "eleven_v4_turbo")
    monkeypatch.setenv("ELEVENLABS_TTS_LANGUAGE", "")
    speaker = ElevenLabsSpeaker(client(lambda r: httpx.Response(200, content=b"\0\0")))
    assert speaker.voice == "V2" and speaker.request_body("x") == {"text": "x", "model_id": "eleven_v4_turbo"}


def test_an_mp3_format_is_converted_to_wav(monkeypatch):
    from waxal_agent import audio
    monkeypatch.setenv("ELEVENLABS_TTS_FORMAT", "mp3_44100_128")
    monkeypatch.setattr(audio, "to_wav", lambda data: b"WAV:" + data)
    seen = []
    speaker = ElevenLabsSpeaker(client(lambda r: seen.append(r) or httpx.Response(200, content=b"MP3DATA")))
    assert speaker.speak("x") == b"WAV:MP3DATA" and seen[0].url.params["output_format"] == "mp3_44100_128"


def test_recognition_is_a_multipart_upload_and_returns_the_text():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"language_code": "wol", "text": " Nanga def? "})
    assert ElevenLabsListener(client(handler)).transcribe(b"RIFFwav") == "Nanga def?"
    request = seen[0]
    assert request.url.path == "/v1/speech-to-text" and request.headers["xi-api-key"] == "KEY"
    for part in (b'name="model_id"', b"scribe_v1", b'name="language_code"', b"wol", b'name="file"', b"RIFFwav"):
        assert part in request.content


def test_a_rejection_shows_elevenlabs_message_and_is_not_retried_for_a_client_error():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(422, json={"detail": {"status": "invalid_language", "message": "language_code not supported"}})
    with pytest.raises(ElevenLabsError, match="language_code not supported") as raised:
        client(handler).post("v1/speech-to-text", data={})
    assert len(calls) == 1 and raised.value.status == 422


def test_a_server_error_is_tried_twice_and_a_limit_starts_a_cooldown():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(502 if request.url.path.endswith("a") else 429, json={"detail": "x"})
    c = client(handler)
    with pytest.raises(ElevenLabsError):
        c.post("a")
    assert len(calls) == 2                                              # 502: two attempts
    with pytest.raises(ElevenLabsError):
        c.post("b")
    with pytest.raises(ElevenLabsError, match="not calling again"):    # 429: no waiting loop, then a cooldown
        c.post("b")
    assert len(calls) == 3


def test_a_missing_key_is_explained(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(ElevenLabsError, match="ELEVENLABS_API_KEY is not set"):
        ElevenLabsClient()


def test_elevenlabs_engines_need_no_soynade_key(monkeypatch):
    monkeypatch.delenv("SOYNADE_API_KEY", raising=False)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    monkeypatch.setenv("WAXAL_STT", "elevenlabs")
    monkeypatch.setenv("WAXAL_TTS", "elevenlabs")
    listener, translator, speaker = build_engines("hosted")
    assert [type(e).__name__ for e in (listener, translator, speaker)] == ["ElevenLabsListener", "ClaudeTranslator", "ElevenLabsSpeaker"]
    assert Pipeline(listener, translator, speaker, agent=None).direct is False       # Wolof text, then translated to English


def test_speech_can_be_streamed_from_the_stream_route_in_a_playable_format():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=b"ID3" + b"\x01" * 100)
    media, audio = ElevenLabsSpeaker(client(handler)).speak_stream("Nanga def?")
    assert media == "audio/mpeg" and b"".join(audio).startswith(b"ID3")
    assert seen[0].url.path == "/v1/text-to-speech/JBFqnCBsd6RMkjVDRZzb/stream" and seen[0].url.params["output_format"] == "mp3_44100_64"


def test_a_refusal_is_raised_before_any_byte_is_streamed():
    def handler(request):
        return httpx.Response(402, json={"detail": {"message": "quota exceeded"}})
    with pytest.raises(ElevenLabsError, match="quota exceeded"):
        ElevenLabsSpeaker(client(handler)).speak_stream("Nanga def?")
