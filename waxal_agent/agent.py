"""One conversation per person, on top of CodeAgent, over one library of documents shared by everybody.

CodeAgent keeps its state in the process (one project at a time), so turns are run one after the other
under a lock: each turn opens the person's own folder (their conversation lives there), adds the shared library as a
read-only folder, resumes their saved conversation, answers, and saves it again. Throughput is one turn at a time per
process: run several processes for more.
"""

import re
import threading
from pathlib import Path

from coding_agent import register_tool, session, state
from coding_agent.common import ToolError

from .links import LinkRefused, allowed_domains, check_link
from .language import REPLY_LANGUAGE, REPLY_LANGUAGE_NAME
from .mt.claude_api import style_guide
from .office_tools import register_office_tools
from .voice_ui import VoiceUI

# Read-only: a public channel must not change or delete files, run programs or browse. Its final reply is the answer.
TOOLS = ["list_directory", "read_file", "grep", "read_pdf", "read_excel", "view_image", "read_word", "read_powerpoint", "ask_human", "share_link", "web_search"]


def _share_link(url: str, label: str = "") -> str:
    try:
        return state.ui.share(check_link(url, label))
    except LinkRefused as e:
        raise ToolError(str(e))


def register_tools() -> None:
    """The application's own tools, added with CodeAgent's register_tool: read_word, read_powerpoint."""
    register_tool({
        "name": "share_link",
        "description": ("Show the person a link to a website, with the answer: it is displayed (and sent as text), never spoken. Use it when "
                        "a website would help them, for example where to find or do something. Only an https link to an allowed website is "
                        "accepted (an error tells you which). Give a short label saying what the link is for."),
        "input_schema": {"type": "object", "properties": {"url": {"type": "string", "description": "The https address."},
                                                          "label": {"type": "string", "description": "What the link is, a few words."}},
                         "required": ["url"]},
    }, _share_link)
    register_office_tools()


register_tools()

SYSTEM_PROMPT = """You are a helpful assistant that talks with people through spoken voice notes. You answer questions about \
the documents of the library, the folder {documents} (the same documents for every person). You can only read them.

Always write in {language}, whatever language the documents are in: when you quote a document, translate what you quote. Your final reply is your answer to the person, and nothing else: {spoken}. So:
- Answer only from information you found in the documents of the library: read the relevant files first (list_directory on {documents}, then read_pdf, read_excel, read_word, read_powerpoint, read_file or view_image, with absolute paths), and base every statement on what they say. Never use outside knowledge, never guess, never fill gaps. If the files do not contain the answer, say so plainly and say what is missing.
- Answer in short, plain sentences, each one simple and brief, and keep the whole answer as short as possible.
- Do not use tables, bullet lists, markdown, code or file paths in the answer. Say numbers and names simply.
- Spell out what matters once; do not repeat yourself.
- If you need a file you cannot find, say so and say what you would need.
- You cannot change files or ask for approvals in this channel. Say clearly when something needs more than reading.
- If you need to ask the person something, use ask_human with one very brief question (a few words, in {language}), then end your turn: they answer by voice in their next message.
The person's words reached you through {heard}, so they may contain mistakes: if a \
request is unclear, ask one very brief question instead of guessing."""
# What happens to the final reply: translated into Wolof (the agent works in English or French), or spoken as it is (WAXAL_REPLY_LANGUAGE=wo).
if REPLY_LANGUAGE == "wo":
    SPOKEN = ("it is spoken aloud exactly as you write it, so write correct Wolof in standard (CAADA) spelling, in short plain "
              "sentences, as it would be said aloud")
    HEARD = "speech recognition"
else:
    SPOKEN = "it is translated into Wolof by a machine and spoken aloud"
    HEARD = "speech recognition and translation"
SYSTEM_PROMPT = SYSTEM_PROMPT.replace("{spoken}", SPOKEN).replace("{heard}", HEARD)
SYSTEM_PROMPT = SYSTEM_PROMPT.replace("{language}", REPLY_LANGUAGE_NAME)  # ({workspace} would be filled in by CodeAgent)


def user_folder(root: Path, user_id: str) -> Path:
    """A folder name that is safe on every system, one per person."""
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", user_id).lstrip(".")[:64] or "user"  # never "." or ".."
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def spoken_reply(reply: str, questions: list[str]) -> str:
    """What is spoken to the person, and nothing else: the question the agent asked (ask_human); else its final reply."""
    asked = [t.strip() for t in questions if t.strip()]
    return "\n".join(asked) if asked else reply.strip()


# Added to every spoken request: the reply is spoken, so shorter is better.
CONCISE = f"Instructions: answer only from what you found in the library documents (say so if it is not there), always answer in {REPLY_LANGUAGE_NAME} (even about documents in another language), be concise, keep your answer as short as possible, in short sentences."


class AgentTurns:
    """Run one instruction for one person and return the written reply."""

    def __init__(self, root: Path | str = "data/users", tools: list[str] | None = None,
                 documents: Path | str | None = None, refresh=None) -> None:
        self.root = Path(root)
        self.refresh = refresh  # refresh(user_id, folder): fetch this person's own documents into folder before a turn
        self.documents = Path(documents).resolve() if documents else None  # the shared library, read-only for the agent
        self.system_prompt = SYSTEM_PROMPT.replace("{documents}", self.documents.as_posix() if self.documents else "{workspace}")
        self.tools = TOOLS if tools is None else tools
        self._lock = threading.Lock()
        self._running = False

    def prompt_for_turn(self) -> str:
        """The system prompt of this turn. When the agent writes the Wolof itself (WAXAL_REPLY_LANGUAGE=wo), the style guide
        (translation_style_prompt.md) is part of it: nobody else translates. Read at every turn, so a change applies at once."""
        style = style_guide() if REPLY_LANGUAGE == "wo" else ""
        domains = allowed_domains()
        links = ((f"\n\nWhen a website would help the person, call share_link with an https address and a short label: the link is shown "
                  f"with your answer and never spoken, so do not read an address aloud or write it in your answer. Only these websites are allowed: "
                  f"{', '.join(domains)}. web_search can help you find the right page.") if domains else "")
        return (self.system_prompt + links
                + (f"\n\nStyle guide for the Wolof you write (follow it):\n{style}" if style else ""))

    def stop(self) -> bool:
        """Stop the turn that is running (it ends at the next model call and is rolled back). False when none is running."""
        if not self._running:
            return False
        session.stop()
        return True

    def ask(self, user_id: str, english: str) -> tuple[str, list[str]]:
        """(the agent's reply, notes about what went wrong or could not be done)."""
        reply, notes, _ = self.ask_full(user_id, english)
        return reply, notes

    def ask_full(self, user_id: str, english: str) -> tuple[str, list[str], list[dict]]:
        """(the reply, the notes, the links the agent shared): the links belong to this turn only."""
        folder = user_folder(self.root, user_id)
        ui = VoiceUI()
        failure = None
        personal = folder / "documents"
        if self.refresh:
            self.refresh(user_id, personal)
        if personal.is_dir() and any(personal.iterdir()):
            english += f"\n\nThis person also has their own documents in {personal.as_posix()}: read them too."
        with self._lock:
            session.open_project(folder, ui=ui, tools=self.tools, system_prompt=self.prompt_for_turn(), resume=True)
            if self.documents:
                self.documents.mkdir(parents=True, exist_ok=True)
                session.add_read_folder(self.documents)
            state.stop_requested = False  # a stop asked for earlier must not abort this turn
            self._running = True
            try:
                session.send(f"{english}\n\n{CONCISE}")
            except Exception as e:  # e.g. no Claude access configured at all
                from coding_agent.errors import describe
                failure = describe(e) or f"{type(e).__name__}: {e}"
            finally:
                self._running = False
                session.close()
        notes = ui.errors + [f"Could not do without approval: {q}" for q in ui.refused]
        if failure:
            notes.append(failure)
        return spoken_reply(ui.reply, ui.questions), notes, ui.links
