"""Languages. A plain value, built from an environment (Settings.from_env reads WAXAL_TRANSLATION / WAXAL_REPLY_LANGUAGE once); nothing here is
read at import time, so two Settings (two languages) can live in the same process.

translation_on=False (WAXAL_TRANSLATION=off; default on): NO translation whatsoever. The turn is speech recognition -> the agent -> voice: the
agent reads what was recognised and answers in reply_language (default fr in this mode), and that text is spoken as it is.

reply_language (WAXAL_REPLY_LANGUAGE; default en, or fr when translation is off): the language the agent works and answers in; every reply of
the agent is forced into it (a document in another language is translated by the agent when it quotes it). With translation on, its text is then
translated into Wolof and spoken. Set wo to have the agent write Wolof itself: nothing is translated either.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

NAMES = {"fr": "French", "en": "English", "wo": "Wolof"}
# ElevenLabs language codes: what the person speaks (recognition) and what is spoken (voice), when nothing is translated.
STT_CODES = {"fr": "fra", "en": "eng", "wo": "wol"}
TTS_CODES = {"fr": "fr", "en": "en", "wo": "fr"}  # no Wolof in eleven_v4: French reads Wolof spelling best


@dataclass(frozen=True)
class Language:
    translation_on: bool = True
    reply_language: str = "en"

    @classmethod
    def from_env(cls, env=None) -> "Language":
        env = os.environ if env is None else env
        translation_on = (env.get("WAXAL_TRANSLATION") or "on").strip().lower() not in ("off", "0", "no", "false")
        reply_language = (env.get("WAXAL_REPLY_LANGUAGE") or "").strip() or ("en" if translation_on else "fr")
        return cls(translation_on, reply_language)

    @property
    def translating(self) -> bool:
        """True when the turn has translation steps. False: the agent reads and writes the language of the person."""
        return self.translation_on and self.reply_language != "wo"

    @property
    def name(self) -> str:
        """How the reply language is named in the start-up message and the prompt; an unknown code is shown as it is."""
        return NAMES.get(self.reply_language, self.reply_language)

    @property
    def source(self) -> str:
        """The source language of the translation into Wolof ("wo": the agent writes Wolof itself, there is nothing to translate)."""
        return self.reply_language

    @property
    def stt_code(self) -> str:
        """What ElevenLabs is told to recognise: Wolof when translating, else the reply language (e.g. "fra")."""
        return "wol" if self.translating else STT_CODES.get(self.reply_language, "wol")

    @property
    def tts_code(self) -> str:
        """What ElevenLabs is told to speak: French (closest to Wolof spelling) when translating, else the reply language."""
        return "fr" if self.translating else TTS_CODES.get(self.reply_language, "fr")
