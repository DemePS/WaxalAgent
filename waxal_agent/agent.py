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

from .language import REPLY_LANGUAGE_NAME
from .office_tools import register_office_tools
from .voice_ui import VoiceUI

# Read-only: a public channel must not change or delete files, run programs or browse. speak_wolof is how it answers.
TOOLS = ["list_directory", "read_file", "grep", "read_pdf", "read_excel", "view_image", "read_word", "read_powerpoint", "ask_human",
         "speak_wolof"]


def _speak_wolof(text: str) -> str:
    return state.ui.speak(text)


def register_tools() -> None:
    """The application's own tools, added with CodeAgent's register_tool: speak_wolof (how the agent answers), read_word, read_powerpoint."""
    register_tool({
        "name": "speak_wolof",
        "description": (f"Say your answer to the person: the text is translated into Wolof and spoken as a voice note. "
                        f"Call it once, with your whole short answer, written in {REPLY_LANGUAGE_NAME}."),
        "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    }, _speak_wolof)
    register_office_tools()


register_tools()

SYSTEM_PROMPT = """You are a helpful assistant that talks with people through spoken voice notes. You answer questions about \
the documents of the library, the folder {documents} (the same documents for every person). You can only read them.

Always write in {language}, whatever language the documents or the person's message are in: when you quote a document, translate what you quote. Give your answer to the person by calling speak_wolof once with the whole answer: it is translated into Wolof by a machine and spoken aloud. So:
- Answer only from information you found in the documents of the library: read the relevant files first (list_directory on {documents}, then read_pdf, read_excel, read_word, read_powerpoint, read_file or view_image, with absolute paths), and base every statement on what they say. Never use outside knowledge, never guess, never fill gaps. If the files do not contain the answer, say so plainly and say what is missing.
- Read the documents again for every question, even if the same or a similar question was asked before in this conversation: earlier answers are not a source, the documents are.
- Answer in short, plain sentences, each one simple and brief, and keep the whole answer as short as possible.
- Do not use tables, bullet lists, markdown, code or file paths in the answer. Say numbers and names simply.
- Spell out what matters once; do not repeat yourself.
- If you need a file you cannot find, say so and say what you would need.
- You cannot change files or ask for approvals in this channel. Say clearly when something needs more than reading.
- If you need to ask the person something, use ask_human with one very brief question (a few words, in {language}), then end your turn: they answer by voice in their next message.
The person's words reached you through speech recognition and translation, so they may contain mistakes: if a \
request is unclear, ask one very brief question instead of guessing."""
SYSTEM_PROMPT = SYSTEM_PROMPT.replace("{language}", REPLY_LANGUAGE_NAME)  # ({workspace} would be filled in by CodeAgent)


HISTORY_TURNS = 6  # earlier exchanges kept in the conversation


def text_history(messages: list, keep: int = HISTORY_TURNS) -> list:
    """The earlier conversation as plain text only: what the person asked and what the agent said (speak_wolof and
    ask_human included). The tool calls and their results are dropped, so that a question asked again is answered by
    reading the documents again, not copied from the tool results of the last time."""
    said = {"speak_wolof": "text", "ask_human": "question"}
    turns: list[dict] = []
    for m in messages:
        blocks = [{"type": "text", "text": m["content"]}] if isinstance(m["content"], str) else m["content"]
        texts = [b["text"] for b in blocks if b.get("type") == "text" and b.get("text")]
        if m["role"] == "assistant":
            texts += [b["input"][said[b["name"]]] for b in blocks
                      if b.get("type") == "tool_use" and b.get("name") in said and said[b["name"]] in b.get("input", {})]
        if not texts:
            continue  # tool results, thinking
        text = "\n".join(texts)
        if turns and turns[-1]["role"] == m["role"]:
            turns[-1]["content"][0]["text"] += "\n" + text
        else:
            turns.append({"role": m["role"], "content": [{"type": "text", "text": text}]})
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    if turns and turns[-1]["role"] == "user":
        turns.pop()  # an unanswered question: the next instruction replaces it
    return turns[-2 * keep:]


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
CONCISE = f"Instructions: read the library documents again for this question; answer only from what you found in the library documents (say so if it is not there), always answer in {REPLY_LANGUAGE_NAME} (even about documents in another language), be concise, keep your answer as short as possible, in short sentences."


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

    def stop(self) -> bool:
        """Stop the turn that is running (it ends at the next model call and is rolled back). False when none is running."""
        if not self._running:
            return False
        session.stop()
        return True

    def ask(self, user_id: str, english: str) -> tuple[str, list[str]]:
        """(the agent's reply in English, notes about what went wrong or could not be done)."""
        folder = user_folder(self.root, user_id)
        ui = VoiceUI()
        failure = None
        personal = folder / "documents"
        if self.refresh:
            self.refresh(user_id, personal)
        if personal.is_dir() and any(personal.iterdir()):
            english += f"\n\nThis person also has their own documents in {personal.as_posix()}: read them too."
        with self._lock:
            session.open_project(folder, ui=ui, tools=self.tools, system_prompt=self.system_prompt, resume=True)
            session.messages[:] = text_history(session.messages)
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
        return spoken_reply(ui.reply, ui.questions, ui.spoken), notes
