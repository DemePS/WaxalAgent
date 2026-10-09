"""The agent's UI for a voice channel: it only collects what Claude says, in writing."""

import logging
import time

from coding_agent.ui import UI

log = logging.getLogger("waxal.agent")


class VoiceUI(UI):
    """Collects Claude's final reply (the text of the last response of a turn).

    Nothing can be approved by voice: an approval gets "no", and the turn's notes say so. The tool set given to the
    agent should not need approvals in the first place.

    A question to the person is just the agent's reply: the turn ends, the question is spoken, and the person answers with their next
    voice note, which resumes the conversation through its saved history. The agent has no ask_human tool here.
    """

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.refused: list[str] = []
        self.links: list[dict] = []  # what the agent shared with share_link: [{"url", "label"}]
        self._chunks: list[str] = []
        self._links_here = False        # this response calls share_link
        self._pending: tuple[str, bool] | None = None  # (text, shared a link) of the response that just ended, until we know why it stopped
        self._responses: list[tuple[str, str | None, bool]] = []  # every response of the turn: (text, why it stopped, shared a link)
        self._started = time.monotonic()  # the turn's clock, for the timing line
        self._first_output: float | None = None  # when the agent first thought, wrote or called a tool
        self.tool_calls = 0

    def _first(self) -> None:
        if self._first_output is None:
            self._first_output = time.monotonic() - self._started

    def log_timing(self) -> None:
        """One line for the measure of a turn: how long before the agent's first output (the set-up of the session, the request to Claude
        and its first reply), and how many tools it called. The number of model calls and the tokens are in CodeAgent's own `tokens:` line."""
        first = "never" if self._first_output is None else f"{self._first_output:.1f} s"
        log.info("   agent timing: first output after %s, %d tool call(s), %.1f s in all", first, self.tool_calls, time.monotonic() - self._started)

    def share(self, link: dict) -> str:
        """The share_link tool: the link is shown to the person with the answer (not spoken). Once per address."""
        if all(link["url"] != known["url"] for known in self.links):
            self.links.append(link)
            log.info("   share_link: %s", link["url"])
        return ("(The link will be shown to the person. Do not read it aloud or write it in your answer. Your last message is what is "
                "spoken: if you have not written your answer yet, write it now, in full.)")

    # what the agent says
    def assistant_start(self) -> None:
        # A response can arrive as several text blocks: the words already collected stay (they are cleared when the response ends).
        self._first()

    def assistant_text(self, text: str) -> None:
        self._chunks.append(text)

    def assistant_end(self) -> None:
        if self._pending:  # the previous response was never given a stop reason (an older CodeAgent): it counts as it always did
            self._responses.append((self._pending[0], None, self._pending[1]))
        self._pending = ("".join(self._chunks).strip(), self._links_here)
        self._chunks = []
        self._links_here = False

    def response_end(self, stop_reason: str | None) -> None:
        """Why the response stopped says what it was. end_turn: the agent is done and this response is its answer. tool_use: it was a step
        (a comment while it works). Anything else (max_tokens, refusal, an interrupted stream): the answer was cut short."""
        text, links = self._pending or ("", False)
        self._pending = None
        self._responses.append((text, stop_reason, links))
        if stop_reason in (None, "end_turn"):
            return
        if text:
            log.info("   agent working (%s): %s", stop_reason, text[:300])
        if stop_reason not in ("tool_use", "pause_turn"):
            self.errors.append(f"The agent's answer was cut short ({stop_reason}).")

    @property
    def knows_why_responses_stopped(self) -> bool:
        """CodeAgent reports the stop reason of each response (an older one does not): only then can we tell that a turn did not finish."""
        return any(stop is not None for _, stop, _ in self._responses)

    @property
    def finished(self) -> bool:
        """The agent ended its turn (a response stopped with end_turn): `reply` is its answer."""
        return any(stop == "end_turn" for _, stop, _ in self._responses)

    @property
    def reply(self) -> str:
        """What is spoken: the text of the response that ended the turn, after what the agent wrote in responses that shared a link (it often
        writes the answer, calls share_link, then ends with a short "here is the link"). The comments it writes while it works (responses that
        stopped for a tool) and anything cut short are not part of it. A response whose stop reason was never reported (an older CodeAgent
        calls only assistant_end) counts as a final one, as it always did."""
        records = [*self._responses, *([(self._pending[0], None, self._pending[1])] if self._pending else [])]
        kept = [text for text, _, links in records if links and text]
        last = next((r for r in reversed(records) if r[0]), None)  # the last response that wrote anything
        final = last[0] if last and not last[2] and last[1] in (None, "end_turn") else ""
        return " ".join(part for part in (*kept, final) if part)

    def thinking(self) -> None:
        self._first()
        log.info("   the agent is thinking...")

    def tool_start(self, name: str) -> None:
        self._first()
        self.tool_calls += 1
        log.info("   tool: %s", name)
        if name == "share_link":
            self._links_here = True

    def tool_result(self, name: str, arguments: str, ok: bool, summary: str) -> None:
        log.log(logging.INFO if ok else logging.WARNING, "   tool %s(%s) -> %s: %s", name, arguments[:200],
                "ok" if ok else "FAILED", summary[:200])

    def message(self, text: str) -> None:
        if text.startswith("[error]"):
            self.errors.append(text.removeprefix("[error]").strip())

    def error(self, text: str) -> None:
        log.error("   agent error: %s", text)
        self.errors.append(text)

    def confirm(self, question: str, choices: tuple[str, ...] = ("yes", "no")) -> str:
        self.refused.append(question.strip())
        return "no" if "no" in choices else choices[-1]

    def ask_text(self, prompt: str, multiline: bool = False) -> str:
        # Nobody can answer during the turn (ask_human is not one of this agent's tools; this is only a safety net).
        return "(Nobody can answer now. Ask your question in your reply, briefly, and finish your turn.)"
