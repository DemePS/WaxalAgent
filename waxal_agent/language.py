"""Languages.
WAXAL_REPLY_LANGUAGE (default en): the language the agent works and answers in; every reply of the agent is forced into it
(a document in another language is translated by the agent when it quotes it). Its text is then translated into Wolof by
Soynade and spoken. Set wo to have the agent write Wolof itself (nothing is translated), or fr for French."""

import os

REPLY_LANGUAGE = os.environ.get("WAXAL_REPLY_LANGUAGE") or "en"
NAMES = {"fr": "French", "en": "English", "wo": "Wolof"}
REPLY_LANGUAGE_NAME = NAMES.get(REPLY_LANGUAGE, REPLY_LANGUAGE)
# The source language of the translation into Wolof ("wo": the agent writes Wolof, there is nothing to translate).
TRANSLATION_SOURCE = REPLY_LANGUAGE
