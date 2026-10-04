"""Wolof <-> English translation: POST /v1/translations on Soynade's API (model oolel-speech-v1).

The documentation lists the route, not its fields, so the JSON body is tried in the shapes such a route most likely has,
until the server accepts one (HTTP 400 / 422 means "not this shape"); the first accepted shape is remembered:

    {"model", "text", "source_language", "target_language"}      language codes "wo" / "en"
    {"model", "input", "source_language", "target_language"}
    {"model", "text", "source", "target"}
    {"model", "input", "source", "target"}
    {"model", "input", "target_language"}

When none is accepted the error shows what Soynade said for each: send it to me and the shape is corrected.
The answer's text is read from translation / translated_text / text / output (or a plain-text body).
"""

import os

from ..soynade_api import SoynadeClient, SoynadeError, text_in

DEFAULT_MODEL = "oolel-speech-v1"
# source_language / target_language are the names Soynade's audio translation route uses: tried first.
SHAPES = (("text", "source_language", "target_language"), ("input", "source_language", "target_language"),
          ("text", "source", "target"), ("input", "source", "target"), ("input", None, "target_language"))


class SoynadeTranslator:
    def __init__(self, client: SoynadeClient | None = None, model: str | None = None) -> None:
        self.client = client or SoynadeClient()
        self.model = model or os.environ.get("SOYNADE_MT_MODEL") or DEFAULT_MODEL
        self._shape = None

    def translate(self, text: str, source: str, target: str) -> str:
        if source == target or not text.strip():
            return text
        shapes = [self._shape] if self._shape else SHAPES
        errors = []
        for shape in shapes:
            text_key, source_key, target_key = shape
            body = {"model": self.model, text_key: text, target_key: target}
            if source_key:
                body[source_key] = source
            try:
                response = self.client.post_json("translations", body)
            except SoynadeError as e:
                if e.status in (400, 422) and not self._shape:
                    errors.append(f"{sorted(body)}: {e}")
                    continue
                raise
            self._shape = shape
            return text_in(response, ("translation", "translated_text", "text", "output"))
        raise SoynadeError("Soynade's /translations rejected every request shape I know:\n  " + "\n  ".join(errors))
