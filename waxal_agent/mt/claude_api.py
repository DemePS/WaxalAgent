"""Translation by Claude (the same Claude the agent uses): the default translator.

One short instruction, temperature 0, and the translation alone as the answer. For Wolof the instruction asks for standard
(CAADA) spelling and plain short sentences, as they would be said aloud, and faithful numbers, names and references.
WAXAL_MT=soynade uses Soynade's /translations route instead. The model is Opus (DEFAULT_MODEL), not the agent's (Sonnet): WAXAL_MT_MODEL picks
another one. On Foundry the model is a deployment name, so there it is the agent's deployment unless WAXAL_MT_MODEL names the Opus one.
"""

import logging
import os
import time
from pathlib import Path

log = logging.getLogger("waxal.translate")

NAMES = {"wo": "Wolof", "en": "English", "fr": "French"}

SYSTEM = {
    "wo": ("You translate text from {source} into Wolof. Write standard (CAADA) Wolof spelling, in short plain sentences, as it "
           "would be said aloud. Keep numbers, names, dates and article references faithful. Reply with the translation only: no "
           "quotes, no notes, no explanation."),
    "other": ("You translate text from {source} into {target}. The text may come from speech recognition and contain small "
              "mistakes: translate what was meant. Keep numbers, names, dates and article references faithful. Reply with the "
              "translation only: no quotes, no notes, no explanation."),
}


STYLE_FILE = "data/translation_style_prompt.md"  # WAXAL_TRANSLATION_STYLE changes it
STYLE_MAX_CHARS = 20_000


def style_guide() -> str:
    """Your own instructions for the Wolof translation, from translation_style_prompt.md (spelling, vocabulary, tone, a glossary,
    examples...). Read at every translation, so a change applies at once; a missing or empty file adds nothing."""
    path = Path(os.environ.get("WAXAL_TRANSLATION_STYLE") or STYLE_FILE)
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if len(text) > STYLE_MAX_CHARS:
        log.warning("%s is longer than %d characters: the rest is ignored.", path, STYLE_MAX_CHARS)
        text = text[:STYLE_MAX_CHARS]
    return text


DEFAULT_MODEL = "claude-opus-5"  # the translation model on Anthropic's API (the agent's default is Sonnet)


def default_model() -> str:
    from coding_agent.config import get_model, uses_anthropic_api
    return DEFAULT_MODEL if uses_anthropic_api() else get_model()


# Tried in this order. Sonnet 5.5 turns thinking off with {"type": "between_tools"} (no other field) and takes no temperature; other
# models take temperature 0, and some take {"type": "disabled"}.
OPTIONS = (
    {"temperature": 0, "thinking": {"type": "between_tools"}},
    {"thinking": {"type": "between_tools"}},
    {"temperature": 0, "thinking": {"type": "disabled"}},
    {"thinking": {"type": "disabled"}},
    {"temperature": 0},
    {},
)


class ClaudeTranslator:
    def __init__(self, client=None, model: str | None = None) -> None:
        self._client = client
        self._model = model or os.environ.get("WAXAL_MT_MODEL")
        self._option = 0  # the first of OPTIONS the model accepted

    def translate(self, text: str, source: str, target: str) -> str:
        if source == target or not text.strip():
            return text
        from coding_agent.config import _get_client
        client = self._client or _get_client()
        names = {"source": NAMES.get(source, source), "target": NAMES.get(target, target)}
        system = SYSTEM["wo" if target == "wo" else "other"].format(**names)
        if target == "wo" and (style := style_guide()):  # appended after format(): braces in the file are safe
            system += "\n\nStyle guide for this translation (follow it; it refines the rules above):\n" + style
        request = {"model": self._model or default_model(), "max_tokens": max(1024, 300 + 3 * len(text)),
                   "system": system,
                   "messages": [{"role": "user", "content": text}]}
        started = time.monotonic()
        reply = self._create(client, request)
        result = _text_of(reply)
        if not result and getattr(reply, "stop_reason", "") == "max_tokens":  # the budget went elsewhere (thinking): more room
            reply = self._create(client, {**request, "max_tokens": request["max_tokens"] * 4})
            result = _text_of(reply)
        log.info("Claude translated %s -> %s (%.1f s, %d chars)", source, target, time.monotonic() - started, len(text))
        if not result:
            kinds = [getattr(b, "type", "?") for b in getattr(reply, "content", [])]
            raise ValueError(f"Claude returned no translation of {text[:80]!r} (stop reason: {getattr(reply, 'stop_reason', '?')}, "
                             f"content: {kinds or 'empty'}, model: {request['model']}).")
        return result

    def _create(self, client, request):
        """Temperature 0, and thinking switched off the way the model allows it (a translation needs none, and a model that thinks by
        default can answer with a thinking block only). A model that refuses a setting is asked again without it, and the first
        combination it accepts is remembered, so only the first call of a process can fail."""
        for i in range(self._option, len(OPTIONS)):
            try:
                reply = client.messages.create(**request, **OPTIONS[i])
            except Exception as e:
                message = str(e).lower()
                if i == len(OPTIONS) - 1 or not ("temperature" in message or "thinking" in message):
                    raise
                continue
            self._option = i
            return reply

def _text_of(reply) -> str:
    return "".join(b.text for b in reply.content if getattr(b, "type", "") == "text").strip()
