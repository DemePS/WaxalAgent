import json

import pytest

from waxal_agent.tts import gradio_space
from waxal_agent.tts.base import SpeechUnavailable
from waxal_agent.tts.gradio_space import GradioSpeaker

INFO = {"named_endpoints": {
    "/other": {"parameters": [{"parameter_name": "n", "component": "Number", "parameter_has_default": True, "parameter_default": 1}],
               "returns": [{"component": "Textbox"}]},
    "/generate": {"parameters": [
        {"parameter_name": "text", "component": "Textbox", "python_type": {"type": "str"}, "parameter_has_default": False},
        {"parameter_name": "temperature", "component": "Slider", "parameter_has_default": True, "parameter_default": 0.3},
        {"parameter_name": "voice", "component": "Audio", "parameter_has_default": True, "parameter_default": None}],
        "returns": [{"component": "Audio"}]}}}


class Client:
    def __init__(self, path, info=INFO):
        self.path, self.info, self.calls = path, info, []

    def view_api(self, return_format="dict", print_info=False):
        return self.info

    def predict(self, api_name, **kwargs):
        self.calls.append((api_name, kwargs))
        return str(self.path)


@pytest.fixture(autouse=True)
def convert(monkeypatch):
    monkeypatch.setattr(gradio_space.audio, "to_wav", lambda raw: b"WAV:" + raw)


def test_the_text_to_audio_endpoint_is_found_and_other_inputs_get_their_defaults(tmp_path):
    wav = tmp_path / "out.wav"
    wav.write_bytes(b"AUDIO")
    client = Client(wav)
    assert GradioSpeaker(client=client).speak("Naka nga def?") == b"WAV:AUDIO"
    assert client.calls == [("/generate", {"text": "Naka nga def?", "temperature": 0.3, "voice": None})]


def test_extra_inputs_come_from_the_environment(tmp_path, monkeypatch):
    wav = tmp_path / "o.wav"
    wav.write_bytes(b"A")
    monkeypatch.setenv("WAXAL_TTS_SPACE_ARGS", json.dumps({"temperature": 0.7}))
    client = Client(wav)
    GradioSpeaker(client=client).speak("x")
    assert client.calls[0][1]["temperature"] == 0.7


def test_an_input_that_cannot_be_filled_is_named():
    info = {"named_endpoints": {"/g": {"parameters": [
        {"parameter_name": "text", "component": "Textbox", "python_type": {"type": "str"}},
        {"parameter_name": "language", "component": "Dropdown", "parameter_has_default": False}], "returns": [{"component": "Audio"}]}}}
    with pytest.raises(SpeechUnavailable, match="'language'.*WAXAL_TTS_SPACE_ARGS"):
        GradioSpeaker(client=Client("x", info)).speak("x")


def test_a_space_without_a_text_to_audio_endpoint_lists_what_it_has():
    info = {"named_endpoints": {"/other": INFO["named_endpoints"]["/other"]}}
    with pytest.raises(SpeechUnavailable, match="no endpoint that takes a text and returns audio.*/other"):
        GradioSpeaker(client=Client("x", info)).speak("x")


def test_a_failing_space_is_no_voice_not_a_crash(tmp_path):
    class Failing(Client):
        def predict(self, api_name, **kwargs):
            raise RuntimeError("GPU quota exceeded")
    with pytest.raises(SpeechUnavailable, match="GPU quota exceeded"):
        GradioSpeaker(client=Failing("x")).speak("x")
    with pytest.raises(SpeechUnavailable, match="returned no audio file"):
        GradioSpeaker(client=Client("not-a-file")).speak("x")


def test_waxal_tts_oolel_demo_chooses_it(monkeypatch):
    from waxal_agent.engines import build_speaker
    monkeypatch.setenv("WAXAL_TTS", "oolel-demo")
    assert type(build_speaker()).__name__ == "GradioSpeaker"
