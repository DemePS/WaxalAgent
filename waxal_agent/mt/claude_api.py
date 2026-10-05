"""Translation by Claude (the same Claude the agent uses): the default translator.

One short instruction, temperature 0, and the translation alone as the answer. For Wolof the instruction asks for standard
(CAADA) spelling and plain short sentences, as they would be said aloud, and faithful numbers, names and references.
WAXAL_MT=soynade uses Soynade's /translations route instead; WAXAL_MT_MODEL picks another Claude model than the agent's.
"""

import logging
import os
import time

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


class ClaudeTranslator:
    def __init__(self, client=None, model: str | None = None) -> None:
        self._client = client
        self._model = model or os.environ.get("WAXAL_MT_MODEL")

    def translate(self, text: str, source: str, target: str) -> str:
        if source == target or not text.strip():
            return text
        from coding_agent.config import _get_client, get_model
        client = self._client or _get_client()
        names = {"source": NAMES.get(source, source), "target": NAMES.get(target, target)}
        request = {"model": self._model or get_model(), "max_tokens": max(1024, 300 + 3 * len(text)),
                   "system": SYSTEM["wo" if target == "wo" else "other"].format(**names),
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

    @staticmethod
    def _create(client, request):
        """Temperature 0 and no thinking (a translation needs none, and a model that thinks by default can answer with a
        thinking block only). A model that refuses one of those settings is asked again without it."""
        options = [{"temperature": 0, "thinking": {"type": "disabled"}}, {"thinking": {"type": "disabled"}}, {"temperature": 0}, {}]
        for i, extra in enumerate(options):
            try:
                return client.messages.create(**request, **extra)
            except Exception as e:
                message = str(e).lower()
                if i == len(options) - 1 or not ("temperature" in message or "thinking" in message):
                    raise


def _text_of(reply) -> str:
    return "".join(b.text for b in reply.content if getattr(b, "type", "") == "text").strip()
