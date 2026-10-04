"""Languages.
WAXAL_REPLY_LANGUAGE (default fr): every reply of the agent to the person is forced into it (fr, en, or wo: the agent writes
Wolof itself, nothing is translated).
WAXAL_DOCUMENT_LANGUAGE (default fr): the language of the person's documents; it is the source language when the agent's
text is translated into Wolof (the agent mostly repeats what the documents say)."""

import os

REPLY_LANGUAGE = os.environ.get("WAXAL_REPLY_LANGUAGE") or "fr"
NAMES = {"fr": "French", "en": "English", "wo": "Wolof"}
REPLY_LANGUAGE_NAME = NAMES.get(REPLY_LANGUAGE, REPLY_LANGUAGE)
DOCUMENT_LANGUAGE = os.environ.get("WAXAL_DOCUMENT_LANGUAGE") or "fr"
# The source language of the translation into Wolof ("wo": the agent writes Wolof, there is nothing to translate).
TRANSLATION_SOURCE = "wo" if REPLY_LANGUAGE == "wo" else DOCUMENT_LANGUAGE
