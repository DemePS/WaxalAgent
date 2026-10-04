"""The agent's UI for a voice channel: it only collects what Claude says, in writing."""

from coding_agent.ui import UI


class VoiceUI(UI):
    """Collects Claude's final reply (the text of the last response of a turn).

    Nothing can be approved by voice: a question the agent cannot do without gets "no", and the turn's
    notes say so. The tool set given to the agent should not need approvals in the first place.
    """

    def __init__(self) -> None:
        self.reply = ""
        self.errors: list[str] = []
        self.refused: list[str] = []
        self._chunks: list[str] = []

    # what the agent says
    def assistant_start(self) -> None:
        self._chunks = []

    def assistant_text(self, text: str) -> None:
        self._chunks.append(text)

    def assistant_end(self) -> None:
        text = "".join(self._chunks).strip()
        if text:
            self.reply = text  # the last non-empty response is the answer (earlier ones are 'let me look')
        self._chunks = []

    def message(self, text: str) -> None:
        if text.startswith("[error]"):
            self.errors.append(text.removeprefix("[error]").strip())

    def error(self, text: str) -> None:
        self.errors.append(text)

    # questions: never answered by voice
    def confirm(self, question: str, choices: tuple[str, ...] = ("yes", "no")) -> str:
        self.refused.append(question.strip())
        return "no" if "no" in choices else choices[-1]

    def ask_text(self, prompt: str, multiline: bool = False) -> str:
        self.refused.append(prompt.strip())
        return ""
