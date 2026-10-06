"""The agent's UI for a voice channel: it only collects what Claude says, in writing."""

import logging

from coding_agent.ui import UI

log = logging.getLogger("waxal.agent")


class VoiceUI(UI):
    """Collects Claude's final reply (the text of the last response of a turn).

    Nothing can be approved by voice: an approval gets "no", and the turn's notes say so. The tool set given to the
    agent should not need approvals in the first place.

    A question the agent asks the person (its ask_human tool) is part of the answer: it is collected in `questions`,
    spoken like any reply, and the person answers it with their next voice note (the conversation is resumed).
    """

    def __init__(self) -> None:
        self.reply = ""
        self.errors: list[str] = []
        self.refused: list[str] = []
        self.questions: list[str] = []
        self.links: list[dict] = []  # what the agent shared with share_link: [{"url", "label"}]
        self._chunks: list[str] = []
        self._kept: list[str] = []      # answers written before a link was shared: they are part of the answer
        self._links_here = False        # this response calls share_link

    def share(self, link: dict) -> str:
        """The share_link tool: the link is shown to the person with the answer (not spoken). Once per address."""
        if all(link["url"] != known["url"] for known in self.links):
            self.links.append(link)
            log.info("   share_link: %s", link["url"])
        return ("(The link will be shown to the person. Do not read it aloud or write it in your answer. Your last message is what is "
                "spoken: if you have not written your answer yet, write it now, in full.)")

    # what the agent says
    def assistant_start(self) -> None:
        self._chunks = []
        self._links_here = False

    def assistant_text(self, text: str) -> None:
        self._chunks.append(text)

    def assistant_end(self) -> None:
        text = "".join(self._chunks).strip()
        if text:
            log.info("   the agent says: %s", text[:300])
            # The last non-empty response is the answer (earlier ones are 'let me look'), except that what the agent wrote in a response that
            # shares a link is its answer too: it often writes the answer, calls share_link, then ends with a short "here is the link".
            if self._links_here:
                self._kept.append(text)
            self.reply = " ".join(self._kept if self._links_here else [*self._kept, text])
        self._chunks = []

    def thinking(self) -> None:
        log.info("   the agent is thinking...")

    def tool_start(self, name: str) -> None:
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

    # questions to the person: sent as part of the reply, answered by the next voice note
    def panel(self, title: str, lines=(), tone: str = "change") -> None:
        if tone == "question" and title.strip():  # ask_human shows its question as a panel, then waits for the answer
            log.info("   the agent asks the person: %s", title.strip())
            self.questions.append(title.strip())

    def confirm(self, question: str, choices: tuple[str, ...] = ("yes", "no")) -> str:
        self.refused.append(question.strip())
        return "no" if "no" in choices else choices[-1]

    def ask_text(self, prompt: str, multiline: bool = False) -> str:
        # Nobody can answer now: the question is already in `questions` and will be spoken.
        return ("(The question has been sent to the person by voice; they will answer in their next message. "
                "Do not wait: finish your turn now, briefly.)")
