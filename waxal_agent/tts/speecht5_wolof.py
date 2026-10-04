"""Wolof speech with a SpeechT5 model fine-tuned on Wolof (needs the `models` extra).

SpeechT5 needs a speaker embedding (an x-vector, 512 numbers) to choose a voice: WAXAL_TTS_SPEAKER points to a .npy
file holding one. Which model and which embedding sound right can only be judged by listening: run
`scripts/check_models.py` and listen to its output files. (The XTTS Wolof model is not supported: its licence may
forbid commercial use, and it needs more than a text input.)
"""

import io
import os
import wave

DEFAULT_MODEL = "bilalfaye/speecht5_tts-wolof"
VOCODER = "microsoft/speecht5_hifigan"
RATE = 16000


class SpeechT5Wolof:
    def __init__(self, model: str | None = None, speaker: str | None = None, device: str | None = None,
                 loader=None) -> None:
        self.model_id = model or os.environ.get("WAXAL_TTS_MODEL") or DEFAULT_MODEL
        self.speaker_file = speaker or os.environ.get("WAXAL_TTS_SPEAKER")
        self.device = device
        self._loader = loader  # tests give a fake returning (processor, model, vocoder, speaker); None: transformers
        self._parts = None

    def _load(self):
        if self._parts is None:
            if self._loader is not None:
                self._parts = self._loader(self.model_id)
            else:
                if not self.speaker_file:
                    raise RuntimeError("Set WAXAL_TTS_SPEAKER to a .npy file with a speaker embedding (512 numbers).")
                from .. import certs
                certs.trust_system_certificates()  # a company proxy re-signs HTTPS
                import numpy
                import torch
                from transformers import SpeechT5ForTextToSpeech, SpeechT5HifiGan, SpeechT5Processor
                processor = SpeechT5Processor.from_pretrained(self.model_id)
                model = SpeechT5ForTextToSpeech.from_pretrained(self.model_id)
                vocoder = SpeechT5HifiGan.from_pretrained(VOCODER)
                speaker = torch.tensor(numpy.load(self.speaker_file), dtype=torch.float32).reshape(1, -1)
                self._parts = (processor, model, vocoder, speaker)
        return self._parts

    def speak(self, text: str) -> bytes:
        processor, model, vocoder, speaker = self._load()
        inputs = processor(text=text, return_tensors="pt")
        speech = model.generate_speech(inputs["input_ids"], speaker, vocoder=vocoder)
        samples = speech.detach().cpu().numpy()
        return _wav(samples)


def _wav(samples) -> bytes:
    import numpy
    pcm = (numpy.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return out.getvalue()
