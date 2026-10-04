"""The language the agent writes its answers and questions in: the source language of the translation to Wolof.
WAXAL_REPLY_LANGUAGE: fr (default), en, or wo (the agent writes Wolof itself: no translation)."""

import os

REPLY_LANGUAGE = os.environ.get("WAXAL_REPLY_LANGUAGE") or "fr"
NAMES = {"fr": "French", "en": "English", "wo": "Wolof"}
REPLY_LANGUAGE_NAME = NAMES.get(REPLY_LANGUAGE, REPLY_LANGUAGE)
