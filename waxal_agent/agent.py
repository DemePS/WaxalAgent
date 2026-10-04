"""One conversation per person, on top of CodeAgent.

CodeAgent keeps its state in the process (one project at a time), so turns are run one after the other
under a lock: each turn opens the person's own folder, resumes their saved conversation, answers, and
saves it again. Throughput is one turn at a time per process: run several processes for more.
"""

import re
import threading
from pathlib import Path

from coding_agent import session

from .voice_ui import VoiceUI

# Read-only: a public channel must not change or delete files, run programs or browse.
TOOLS = ["list_directory", "read_file", "grep", "read_pdf", "read_excel", "view_image", "ask_human"]

SYSTEM_PROMPT = """You are a helpful assistant that talks with people through spoken voice notes. You work in the \
folder {workspace} and can read the files in it.

Your English reply is translated into Wolof by a machine and then spoken aloud. So:
- Answer in short, plain sentences. Two to five sentences is usually enough.
- Do not use tables, bullet lists, markdown, code or file paths in the answer. Say numbers and names simply.
- Spell out what matters once; do not repeat yourself.
- If you need a file you cannot find, say so and say what you would need.
- You cannot change files or ask for approvals in this channel. Say clearly when something needs more than reading.
The person's words reached you through speech recognition and translation, so they may contain mistakes: if a \
request is unclear, ask one short question instead of guessing."""


def user_folder(root: Path, user_id: str) -> Path:
    """A folder name that is safe on every system, one per person."""
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", user_id).lstrip(".")[:64] or "user"  # never "." or ".."
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


class AgentTurns:
    """Run one instruction for one person and return the written reply."""

    def __init__(self, root: Path | str = "data/users", tools: list[str] | None = None) -> None:
        self.root = Path(root)
        self.tools = TOOLS if tools is None else tools
        self._lock = threading.Lock()

    def ask(self, user_id: str, english: str) -> tuple[str, list[str]]:
        """(the agent's reply in English, notes about what went wrong or could not be done)."""
        folder = user_folder(self.root, user_id)
        ui = VoiceUI()
        with self._lock:
            session.open_project(folder, ui=ui, tools=self.tools, system_prompt=SYSTEM_PROMPT, resume=True)
            try:
                session.send(english)
            finally:
                session.close()
        notes = ui.errors + [f"Could not do without approval: {q}" for q in ui.refused]
        return ui.reply, notes
