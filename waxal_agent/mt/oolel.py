"""Wolof <-> English translation with Soynade Research's Oolel language model (needs the `models` extra).

Oolel is a Qwen 2.5 based chat model trained for Wolof, with English <-> Wolof translation among its skills. It is asked
with a system prompt: "Translate to Wolof the following sentence" is the one Soynade's own translation pipeline uses; the
opposite direction is assumed to be the mirror sentence (unverified: set WAXAL_MT_PROMPT_WO_EN / WAXAL_MT_PROMPT_EN_WO if
Soynade's model card says otherwise). Low temperature is recommended for consistent translations: decoding here is greedy.

Licence: Soynade's translation pipeline is published under AGPL-3.0, and the licence of each model is its own: read the
model cards before running this for other people (AGPL asks you to offer your source to the users of a network service).
"""

import os

DEFAULT_MODEL = "soynade-research/Oolel-Small-v0.1"
PROMPTS = {"en-wo": "Translate to Wolof the following sentence",
           "wo-en": "Translate to English the following sentence"}


class Oolel:
    def __init__(self, model: str | None = None, device: str | None = None, loader=None) -> None:
        self.model_id = model or os.environ.get("WAXAL_MT_MODEL") or DEFAULT_MODEL
        self.device = device
        self.prompts = {
            "en-wo": os.environ.get("WAXAL_MT_PROMPT_EN_WO") or PROMPTS["en-wo"],
            "wo-en": os.environ.get("WAXAL_MT_PROMPT_WO_EN") or PROMPTS["wo-en"],
        }
        self._loader = loader  # tests give a fake returning (tokenizer, model); None: transformers
        self._parts = None

    def _load(self):
        if self._parts is None:
            if self._loader is not None:
                self._parts = self._loader(self.model_id)
            else:
                from . import certs_for_models
                certs_for_models()
                from transformers import AutoModelForCausalLM, AutoTokenizer
                tokenizer = AutoTokenizer.from_pretrained(self.model_id)
                model = AutoModelForCausalLM.from_pretrained(self.model_id, torch_dtype="auto")
                if self.device:
                    model = model.to(self.device)
                self._parts = (tokenizer, model)
        return self._parts

    def translate(self, text: str, source: str, target: str) -> str:
        if source == target or not text.strip():
            return text
        tokenizer, model = self._load()
        messages = [{"role": "system", "content": self.prompts[f"{source}-{target}"]},
                    {"role": "user", "content": text}]
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer([prompt], return_tensors="pt")
        if self.device:
            inputs = inputs.to(self.device)
        generated = model.generate(**inputs, max_new_tokens=256, do_sample=False)
        new_tokens = [out[len(inp):] for inp, out in zip(inputs["input_ids"], generated)]
        return tokenizer.batch_decode(new_tokens, skip_special_tokens=True)[0].strip()
