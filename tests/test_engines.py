"""The real-model engines, with the model libraries replaced: the glue is tested, not the models."""

import io
import wave

import pytest

from waxal_agent.mt.nllb import Nllb
from waxal_agent.stt.whisper_wolof import WhisperWolof
from waxal_agent.tts.speecht5_wolof import SpeechT5Wolof


class FakeTokenizer:
    src_lang = None

    def __init__(self):
        self.seen = []

    def __call__(self, text, return_tensors=None):
        self.seen.append((self.src_lang, text))
        return {"text": text}

    def convert_tokens_to_ids(self, code):
        return f"id:{code}"

    def batch_decode(self, generated, skip_special_tokens=True):
        return [f" {generated} "]


class FakeModel:
    def generate(self, text, forced_bos_token_id, **options):
        return f"{text}->{forced_bos_token_id}"


def test_nllb_sets_the_source_language_and_forces_the_target():
    tokenizer = FakeTokenizer()
    mt = Nllb(loader=lambda model: (tokenizer, FakeModel()))
    assert mt.translate("jox ma total bi", "wo", "en") == "jox ma total bi->id:eng_Latn"
    assert tokenizer.seen == [("wol_Latn", "jox ma total bi")]
    assert mt.translate("Hello", "en", "wo") == "Hello->id:wol_Latn" and tokenizer.seen[-1][0] == "eng_Latn"


def test_nllb_skips_empty_text_and_same_language():
    mt = Nllb(loader=lambda model: pytest.fail("the model must not load"))
    assert mt.translate("   ", "wo", "en") == "   " and mt.translate("x", "en", "en") == "x"


def test_nllb_model_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("WAXAL_MT_MODEL", "me/my-nllb")
    seen = []
    Nllb(loader=lambda model: seen.append(model) or (FakeTokenizer(), FakeModel())).translate("a", "en", "wo")
    assert seen == ["me/my-nllb"]


def test_whisper_hands_the_samples_to_the_recogniser():
    np = pytest.importorskip("numpy")
    pytest.importorskip("soundfile")
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
        w.writeframes(b"\x00\x10" * 1600)
    calls = []
    asr = WhisperWolof(loader=lambda model: lambda audio: calls.append(audio) or {"text": " nanga def "})
    assert asr.transcribe(out.getvalue()) == "nanga def"
    assert calls[0]["sampling_rate"] == 16000 and isinstance(calls[0]["raw"], np.ndarray) and len(calls[0]["raw"]) == 1600


def test_speecht5_returns_a_valid_wav():
    np = pytest.importorskip("numpy")

    class Out:
        def detach(self): return self
        def cpu(self): return self
        def numpy(self): return np.sin(np.linspace(0, 40, 8000)).astype("float32")

    class Model:
        def generate_speech(self, ids, speaker, vocoder=None):
            return Out()

    parts = (lambda text, return_tensors: {"input_ids": text}, Model(), object(), object())
    wav = SpeechT5Wolof(loader=lambda model: parts).speak("nanga def")
    with wave.open(io.BytesIO(wav)) as w:
        assert w.getframerate() == 16000 and w.getnframes() == 8000


def test_speecht5_asks_for_a_speaker_file_when_none_is_given(monkeypatch):
    monkeypatch.delenv("WAXAL_TTS_SPEAKER", raising=False)
    with pytest.raises(RuntimeError, match="WAXAL_TTS_SPEAKER"):
        SpeechT5Wolof().speak("x")
