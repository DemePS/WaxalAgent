"""Soynade engines with the model libraries replaced: the glue (prompts, arguments, audio) is tested, not the models."""

import io
import wave

import pytest

from waxal_agent.engines import build_engines
from waxal_agent.mt.oolel import Oolel
from waxal_agent.stt.whisper_wolof import SOYNADE_MODEL, WhisperWolof
from waxal_agent.tts.oolel_voices import OolelVoices


class Tokenizer:
    def __init__(self):
        self.messages = []

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
        self.messages.append(messages)
        return "PROMPT"

    def __call__(self, prompts, return_tensors=None):
        return {"input_ids": [[1, 2, 3]]}

    def batch_decode(self, tokens, skip_special_tokens=True):
        return [f"  decoded:{tokens[0]}  "]


class Model:
    def generate(self, input_ids, max_new_tokens, do_sample):
        assert do_sample is False                       # greedy: consistent translations
        return [[1, 2, 3, 9, 8]]                        # the prompt, then the answer


def test_oolel_asks_with_the_system_prompt_of_each_direction_and_decodes_only_the_answer():
    tokenizer = Tokenizer()
    mt = Oolel(loader=lambda model: (tokenizer, Model()))
    assert mt.translate("Hello", "en", "wo") == "decoded:[9, 8]"
    assert mt.translate("naka nga def", "wo", "en") == "decoded:[9, 8]"
    assert tokenizer.messages[0] == [{"role": "system", "content": "Translate to Wolof the following sentence"},
                                     {"role": "user", "content": "Hello"}]
    assert tokenizer.messages[1][0]["content"] == "Translate to English the following sentence"


def test_oolel_prompts_and_model_can_be_changed_from_the_environment(monkeypatch):
    monkeypatch.setenv("WAXAL_MT_MODEL", "me/oolel")
    monkeypatch.setenv("WAXAL_MT_PROMPT_WO_EN", "Translate from Wolof to English:")
    seen, tokenizer = [], Tokenizer()
    mt = Oolel(loader=lambda model: seen.append(model) or (tokenizer, Model()))
    mt.translate("x", "wo", "en")
    assert seen == ["me/oolel"] and tokenizer.messages[0][0]["content"] == "Translate from Wolof to English:"


def test_oolel_skips_empty_text_and_same_language():
    mt = Oolel(loader=lambda model: pytest.fail("the model must not load"))
    assert mt.translate("  ", "en", "wo") == "  " and mt.translate("a", "wo", "wo") == "a"


class Voice:
    sr = 24000

    def __init__(self):
        self.calls = []

    def generate(self, text, **kwargs):
        np = pytest.importorskip("numpy")
        self.calls.append((text, kwargs))
        return np.sin(np.linspace(0, 100, 24000)).astype("float32").reshape(1, -1)


def test_oolel_voices_passes_the_text_voice_and_options_and_returns_wav():
    pytest.importorskip("numpy")
    model = Voice()
    wav = OolelVoices(voice="me.wav", loader=lambda m: model).speak("nanga def")
    assert model.calls == [("nanga def", {"cfg_weight": 0.5, "exaggeration": 0.2, "temperature": 0.3,
                                          "audio_prompt_path": "me.wav"})]
    with wave.open(io.BytesIO(wav)) as w:
        assert w.getframerate() == 24000 and w.getnframes() == 24000


def test_oolel_voices_without_a_voice_prompt_and_with_options_from_the_environment(monkeypatch):
    pytest.importorskip("numpy")
    monkeypatch.setenv("WAXAL_TTS_TEMPERATURE", "0.7")
    monkeypatch.delenv("WAXAL_TTS_VOICE", raising=False)
    model = Voice()
    OolelVoices(loader=lambda m: model).speak("x")
    assert "audio_prompt_path" not in model.calls[0][1] and model.calls[0][1]["temperature"] == 0.7


def test_the_soynade_asr_model_is_the_default_of_the_soynade_engines(monkeypatch):
    monkeypatch.delenv("WAXAL_ASR_MODEL", raising=False)
    listener, translator, speaker = build_engines("soynade")
    assert isinstance(listener, WhisperWolof) and listener.model == SOYNADE_MODEL == "soynade-research/Wolof-HuBERT-CTC"
    assert isinstance(translator, Oolel) and isinstance(speaker, OolelVoices)


def test_engine_names():
    assert [type(e).__name__ for e in build_engines("fake")] == ["FakeListener", "FakeTranslator", "FakeSpeaker"]
    with pytest.raises(SystemExit, match="Unknown engines"):
        build_engines("nope")
