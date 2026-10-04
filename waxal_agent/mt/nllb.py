"""Wolof <-> English translation with NLLB-200 (needs the `models` extra). Fine-tuned Wolof variants can be used
through WAXAL_MT_MODEL; the language codes are the same (wol_Latn, eng_Latn)."""

import os

DEFAULT_MODEL = "facebook/nllb-200-distilled-600M"
CODES = {"wo": "wol_Latn", "en": "eng_Latn"}


class Nllb:
    def __init__(self, model: str | None = None, device: str | None = None, loader=None) -> None:
        self.model_id = model or os.environ.get("WAXAL_MT_MODEL") or DEFAULT_MODEL
        self.device = device
        self._loader = loader  # tests give a fake returning (tokenizer, model); None: transformers
        self._tokenizer = self._model = None

    def _load(self):
        if self._model is None:
            if self._loader is not None:
                self._tokenizer, self._model = self._loader(self.model_id)
            else:
                from .. import certs
                certs.trust_system_certificates()  # a company proxy re-signs HTTPS
                from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
                self._tokenizer = AutoTokenizer.from_pretrained(self.model_id)
                self._model = AutoModelForSeq2SeqLM.from_pretrained(self.model_id)
                if self.device:
                    self._model = self._model.to(self.device)
        return self._tokenizer, self._model

    def translate(self, text: str, source: str, target: str) -> str:
        if source == target or not text.strip():
            return text
        tokenizer, model = self._load()
        tokenizer.src_lang = CODES[source]
        inputs = tokenizer(text, return_tensors="pt")
        if self.device:
            inputs = inputs.to(self.device)
        generated = model.generate(**inputs, forced_bos_token_id=tokenizer.convert_tokens_to_ids(CODES[target]),
                                   max_new_tokens=256, num_beams=4)
        return tokenizer.batch_decode(generated, skip_special_tokens=True)[0].strip()
