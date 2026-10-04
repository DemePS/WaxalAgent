"""Wolof speech recognition with a Whisper model fine-tuned on Wolof (needs the `models` extra: transformers, torch).

Not run in this repository's tests with a real model (no network to the model hub there): `scripts/check_models.py`
runs every stage on your PC and says what it heard and how long it took.
"""

import io
import os

DEFAULT_MODEL = "M9and2M/whisper-small-wolof"


class WhisperWolof:
    def __init__(self, model: str | None = None, device: str | None = None, loader=None) -> None:
        self.model = model or os.environ.get("WAXAL_ASR_MODEL") or DEFAULT_MODEL
        self.device = device
        self._loader = loader  # tests give a fake; None: transformers
        self._pipe = None

    def _load(self):
        if self._pipe is None:
            if self._loader is not None:
                self._pipe = self._loader(self.model)
            else:
                from .. import certs
                certs.trust_system_certificates()  # a company proxy re-signs HTTPS
                from transformers import pipeline
                self._pipe = pipeline("automatic-speech-recognition", model=self.model, device=self.device,
                                      chunk_length_s=30)
        return self._pipe

    def transcribe(self, wav: bytes) -> str:
        import soundfile  # in the `models` extra
        samples, rate = soundfile.read(io.BytesIO(wav), dtype="float32")
        out = self._load()({"raw": samples, "sampling_rate": rate})
        return str(out["text"]).strip()
