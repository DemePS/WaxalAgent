"""One conversation per person, on top of CodeAgent.

CodeAgent keeps its state in the process (one project at a time), so turns are run one after the other
under a lock: each turn opens the person's own folder, resumes their saved conversation, answers, and
saves it again. Throughput is one turn at a time per process: run several processes for more.
"""

import re
import threading
from pathlib import Path

from coding_agent import session

from .language import REPLY_LANGUAGE_NAME
from .voice_ui import VoiceUI

# Read-only: a public channel must not change or delete files, run programs or browse. speak_wolof is how it answers.
TOOLS = ["list_directory", "read_file", "grep", "read_pdf", "read_excel", "view_image", "ask_human", "speak_wolof"]


def register_speak_wolof() -> None:
    """Add the speak_wolof tool to CodeAgent's tool tables (it has no plug-in point; both are plain module-level objects)."""
    from coding_agent import schemas, state
    from coding_agent.tools import TOOL_HANDLERS
    if any(t["name"] == "speak_wolof" for t in schemas.TOOLS):
        return
    schemas.TOOLS.append({
        "name": "speak_wolof",
        "description": (f"Say your answer to the person: the text is translated into Wolof and spoken as a voice note. "
                        f"Call it once, with your whole short answer, written in {REPLY_LANGUAGE_NAME}."),
        "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    })
    TOOL_HANDLERS["speak_wolof"] = lambda text: state.ui.speak(text)


register_speak_wolof()

SYSTEM_PROMPT = """You are a helpful assistant that talks with people through spoken voice notes. You work in the \
folder {workspace} and can read the files in it.

Give your answer to the person by calling speak_wolof once with the whole answer, written in {language}: it is translated into Wolof by a machine and spoken aloud. So:
- Answer in short, plain sentences, each one simple and brief, and keep the whole answer as short as possible.
- Do not use tables, bullet lists, markdown, code or file paths in the answer. Say numbers and names simply.
- Spell out what matters once; do not repeat yourself.
- If you need a file you cannot find, say so and say what you would need.
- You cannot change files or ask for approvals in this channel. Say clearly when something needs more than reading.
- If you need to ask the person something, use ask_human with one very brief question (a few words, in {language}), then end your turn: they answer by voice in their next message.
The person's words reached you through speech recognition and translation, so they may contain mistakes: if a \
request is unclear, ask one very brief question instead of guessing."""
SYSTEM_PROMPT = SYSTEM_PROMPT.replace("{language}", REPLY_LANGUAGE_NAME)  # ({workspace} is filled in by CodeAgent)


def user_folder(root: Path, user_id: str) -> Path:
    """A folder name that is safe on every system, one per person."""
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", user_id).lstrip(".")[:64] or "user"  # never "." or ".."
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def spoken_reply(reply: str, questions: list[str], spoken: list[str] = ()) -> str:
    """What goes to Soynade and then to the person, and nothing else: the question the agent asked (ask_human); else
    what it said with speak_wolof; else its final reply."""
    for texts in (questions, spoken):
        asked = [t.strip() for t in texts if t.strip()]
        if asked:
            return "\n".join(asked)
    return reply.strip()


# Added to every spoken request: the reply is translated and spoken, so shorter is better.
CONCISE = f"Instructions: answer in {REPLY_LANGUAGE_NAME}, be concise, keep your answer as short as possible, in short sentences."


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
        failure = None
        with self._lock:
            session.open_project(folder, ui=ui, tools=self.tools, system_prompt=SYSTEM_PROMPT, resume=True)
            try:
                session.send(f"{english}\n\n{CONCISE}")
            except Exception as e:  # e.g. no Claude access configured at all
                from coding_agent.errors import describe
                failure = describe(e) or f"{type(e).__name__}: {e}"
            finally:
                session.close()
        notes = ui.errors + [f"Could not do without approval: {q}" for q in ui.refused]
        if failure:
            notes.append(failure)
        return spoken_reply(ui.reply, ui.questions, ui.spoken), notes
