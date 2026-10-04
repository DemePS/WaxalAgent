"""Wolof speech with Soynade Research's Oolel-Voices (needs the `models` extra).

Oolel-Voices is a Wolof text-to-speech model that clones the style of a short reference recording (a voice prompt).
Loading follows its model card as far as I could read it without access to the model hub: `snapshot_download`, then
`AutoModel.from_pretrained(path, trust_remote_code=True)` (its code comes from the model repository: you are running
code published there), then `model.generate(text, audio_prompt_path=..., cfg_weight=0.5, exaggeration=0.2,
temperature=0.3)`. Details I could not confirm are guarded and configurable:

    WAXAL_TTS_MODEL      model repository (default soynade-research/Oolel-Voices)
    WAXAL_TTS_VOICE      a short WAV of the voice to imitate (omit it to use the model's own voice, if it has one)
    WAXAL_TTS_RATE       sample rate of the generated audio if the model does not report it (default 24000)

`scripts/check_models.py` writes check_*.wav files: listen to them, and adjust cfg_weight / exaggeration / temperature
(WAXAL_TTS_CFG, WAXAL_TTS_EXAGGERATION, WAXAL_TTS_TEMPERATURE) to taste.
"""

import io
import os
import wave

DEFAULT_MODEL = "soynade-research/Oolel-Voices"


class OolelVoices:
    def __init__(self, model: str | None = None, voice: str | None = None, loader=None) -> None:
        self.model_id = model or os.environ.get("WAXAL_TTS_MODEL") or DEFAULT_MODEL
        self.voice = voice or os.environ.get("WAXAL_TTS_VOICE") or None
        self.options = {"cfg_weight": float(os.environ.get("WAXAL_TTS_CFG") or 0.5),
                        "exaggeration": float(os.environ.get("WAXAL_TTS_EXAGGERATION") or 0.2),
                        "temperature": float(os.environ.get("WAXAL_TTS_TEMPERATURE") or 0.3)}
        self._loader = loader  # tests give a fake returning the model; None: huggingface_hub + transformers
        self._model = None

    def _load(self):
        if self._model is None:
            if self._loader is not None:
                self._model = self._loader(self.model_id)
            else:
                from . import certs_for_models
                certs_for_models()
                from huggingface_hub import snapshot_download
                from transformers import AutoModel
                path = snapshot_download(repo_id=self.model_id)
                self._model = AutoModel.from_pretrained(path, trust_remote_code=True)
        return self._model

    def speak(self, text: str) -> bytes:
        model = self._load()
        kwargs = dict(self.options)
        if self.voice:
            kwargs["audio_prompt_path"] = self.voice
        audio = model.generate(text, **kwargs)
        rate = int(getattr(model, "sr", None) or os.environ.get("WAXAL_TTS_RATE") or 24000)
        return to_wav(audio, rate)


def to_wav(audio, rate: int) -> bytes:
    """A waveform (a torch tensor or a numpy array, mono, floats in -1..1) as 16-bit WAV bytes."""
    import numpy
    if hasattr(audio, "detach"):
        audio = audio.detach().cpu().numpy()
    samples = numpy.asarray(audio, dtype="float32").reshape(-1)
    pcm = (numpy.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return out.getvalue()
