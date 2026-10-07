import io
import wave

from waxal_agent.mt.fake import FakeTranslator
from waxal_agent.pipeline import Pipeline
from waxal_agent.stt.fake import FakeListener
from waxal_agent.tts.fake import FakeSpeaker


class StubAgent:
    def __init__(self, reply="Total is 642 euros. The invoice is paid.", notes=()):
        self.reply, self.notes, self.asked = reply, list(notes), []

    def ask(self, user_id, english):
        self.asked.append((user_id, english))
        return self.reply, self.notes


def make(listener=None, translator=None, agent=None):
    return Pipeline(listener or FakeListener(default="wolof words"), translator or FakeTranslator(),
                    FakeSpeaker(), agent or StubAgent())


def seconds(wav: bytes) -> float:
    with wave.open(io.BytesIO(wav)) as w:
        return w.getnframes() / w.getframerate()


def test_a_wolof_text_goes_to_english_then_back():
    table = {("jox ma total bi.", "wo", "en"): "give me the total."}
    agent = StubAgent()
    pipeline = make(translator=FakeTranslator(table), agent=agent)
    result = pipeline.from_wolof("alice", "jox ma total bi.")
    assert agent.asked == [("alice", "give me the total.")]
    assert result.wolof == "jox ma total bi." and result.english == "give me the total."
    assert result.reply_wolof == "[wo] Total is 642 euros. The invoice is paid."   # one translation call, not one per sentence
    assert seconds(result.audio_wav) > 0.5 and result.notes == []


def test_only_speakable_text_is_translated_and_spoken():
    agent = StubAgent("The total is 642.\n```\nsecret code\n```\n| a | b |")
    translator, pipeline_speaker = FakeTranslator(), FakeSpeaker()
    pipeline = Pipeline(FakeListener(default="x"), translator, pipeline_speaker, agent)
    result = pipeline.from_wolof("u", "naka")
    assert result.reply_english.startswith("The total")           # the written reply is kept whole
    assert pipeline_speaker.spoken == ["[wo] The total is 642."]  # but only plain sentences are spoken


def test_silence_is_answered_without_calling_the_agent():
    agent = StubAgent()
    result = make(agent=agent).from_wolof("u", "   ")
    assert agent.asked == [] and result.notes == ["nothing was heard"] and result.audio_wav


def test_notes_from_the_agent_are_passed_on():
    result = make(agent=StubAgent(notes=["Claude is unreachable"])).from_wolof("u", "naka")
    assert "Claude is unreachable" in result.notes


def test_a_recording_is_converted_then_listened_to(monkeypatch):
    from waxal_agent import audio, pipeline as module
    monkeypatch.setattr(module.audio, "to_wav", lambda data: b"WAV" + data)
    listener = FakeListener("nanga def")
    result = Pipeline(listener, FakeTranslator(), FakeSpeaker(), StubAgent()).from_audio("u", b"abc")
    assert listener.heard == [6] and result.wolof == "nanga def"


def test_long_wolof_replies_are_spoken_in_pieces_of_at_most_450_characters():
    from waxal_agent.pipeline import Pipeline, TurnResult, SPEECH_LIMIT
    import io, wave
    spoken = []

    class Voice:
        def speak(self, text):
            spoken.append(text)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000), w.writeframes(b"\0\0")
            return buf.getvalue()
    pipe = Pipeline.__new__(Pipeline)
    pipe.speaker = Voice()
    pipe._speak([" ".join(["Nanga def, mangi fi rekk."] * 60)], TurnResult())
    assert len(spoken) > 1 and all(len(p) <= SPEECH_LIMIT for p in spoken)


def test_wavs_with_a_streaming_header_are_joined():
    import io, struct, wave
    from waxal_agent.pipeline import _join_wavs
    pcm = b"\x01\x00" * 100
    header = b"RIFF" + struct.pack("<L", 0xFFFFFFFF) + b"WAVEfmt " + struct.pack("<LHHLLHH", 16, 1, 1, 16000, 32000, 2, 16)
    streamed = header + b"data" + struct.pack("<L", 0xFFFFFFFF) + pcm
    for count in (1, 2):
        with wave.open(io.BytesIO(_join_wavs([streamed] * count))) as w:
            assert w.getnframes() == 100 * count and w.getframerate() == 16000


def test_a_failing_speech_service_still_delivers_the_texts():
    from waxal_agent.soynade_api import SoynadeError
    from waxal_agent.pipeline import Pipeline, TurnResult
    class Broken:
        def speak(self, text):
            raise SoynadeError("HTTP 502: soynade.ai | 502: Bad gateway")
    pipe = Pipeline.__new__(Pipeline)
    pipe.speaker = Broken()
    result = TurnResult()
    assert pipe._speak(["Nanga def"], result) == b"" and "502" in result.notes[0]


def test_an_html_error_page_is_shown_as_its_title():
    import httpx
    from waxal_agent.soynade_api import _detail
    page = "<html><head><title>soynade.ai | 502: Bad gateway</title></head><body>...</body></html>"
    assert _detail(httpx.Response(502, text=page)) == "soynade.ai | 502: Bad gateway"


def test_texts_can_be_delivered_before_the_voice():
    from waxal_agent.pipeline import Pipeline
    from waxal_agent.mt.fake import FakeTranslator
    from waxal_agent.stt.fake import FakeListener
    from waxal_agent.tts.fake import FakeSpeaker

    class Agent:
        def ask(self, user, english):
            return "The total is 642.", []
    speaker = FakeSpeaker()
    pipe = Pipeline(FakeListener(default="x"), FakeTranslator(), speaker, Agent())
    result = pipe.from_wolof("u", "naka", speak=False)
    assert result.reply_wolof == "[wo] The total is 642." and result.audio_wav == b"" and speaker.spoken == []
    wav, notes = pipe.speak_text(result.reply_wolof)
    assert wav and notes == [] and speaker.spoken == ["[wo] The total is 642."]


def test_the_start_up_message_reports_the_real_engines(monkeypatch):
    from waxal_agent.engines import describe_engines
    for name in ("WAXAL_STT", "WAXAL_MT", "WAXAL_TTS"):
        monkeypatch.delenv(name, raising=False)
    assert describe_engines("fake") == {"stt": "stand-in", "mt": "stand-in", "tts": "stand-in"}
    assert describe_engines("soynade-asr") == {"stt": "soynade", "mt": "stand-in", "tts": "stand-in"}
    assert describe_engines("hosted") == {"stt": "elevenlabs", "mt": "claude", "tts": "elevenlabs"}
    monkeypatch.setenv("WAXAL_MT", "Soynade")
    monkeypatch.setenv("WAXAL_TTS", "Soynade")
    assert describe_engines("hosted") == {"stt": "elevenlabs", "mt": "soynade", "tts": "soynade"}


def test_a_key_in_a_dot_env_file_is_seen_before_the_engines_are_chosen(tmp_path, monkeypatch):
    from waxal_agent.cli import load_env
    (tmp_path / ".env").write_text("ELEVENLABS_API_KEY=from-the-file\nWAXAL_TEST_SET=file\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    monkeypatch.setenv("WAXAL_TEST_SET", "environment")  # a real variable wins over the file
    load_env()
    import os
    assert os.environ["ELEVENLABS_API_KEY"] == "from-the-file" and os.environ["WAXAL_TEST_SET"] == "environment"
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)


def test_the_pdf_library_does_not_flood_the_terminal_with_font_warnings():
    import logging
    from waxal_agent.cli import quiet_loggers
    quiet_loggers()
    for name in ("pypdf", "pypdf._cmap", "httpx", "azure.identity"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING, name
    assert not logging.getLogger("pypdf._cmap").isEnabledFor(logging.WARNING)
