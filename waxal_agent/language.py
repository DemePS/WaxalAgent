"""Languages.

WAXAL_TRANSLATION=off (default on): NO translation whatsoever. The turn is speech recognition -> the agent -> voice: the agent reads what was
recognised and answers in WAXAL_REPLY_LANGUAGE (default fr in this mode), and that text is spoken as it is.

WAXAL_REPLY_LANGUAGE (default en, or fr when translation is off): the language the agent works and answers in; every reply of the agent is
forced into it (a document in another language is translated by the agent when it quotes it). With translation on, its text is then translated into
Wolof and spoken. Set wo to have the agent write Wolof itself: nothing is translated either.
"""

import os

TRANSLATION_ON = (os.environ.get("WAXAL_TRANSLATION") or "on").strip().lower() not in ("off", "0", "no", "false")
REPLY_LANGUAGE = os.environ.get("WAXAL_REPLY_LANGUAGE") or ("en" if TRANSLATION_ON else "fr")
NAMES = {"fr": "French", "en": "English", "wo": "Wolof"}
REPLY_LANGUAGE_NAME = NAMES.get(REPLY_LANGUAGE, REPLY_LANGUAGE)
# The source language of the translation into Wolof ("wo": the agent writes Wolof, there is nothing to translate).
TRANSLATION_SOURCE = REPLY_LANGUAGE
# ElevenLabs language codes: what the person speaks (recognition) and what is spoken (voice), when nothing is translated.
STT_CODES = {"fr": "fra", "en": "eng", "wo": "wol"}
TTS_CODES = {"fr": "fr", "en": "en", "wo": "fr"}  # no Wolof in eleven_v4: French reads Wolof spelling best


def translating() -> bool:
    """True when the turn has translation steps. False: the agent reads and writes the language of the person."""
    return TRANSLATION_ON and REPLY_LANGUAGE != "wo"
