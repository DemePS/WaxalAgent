"""AgentTurns on top of the real CodeAgent session, with the model call replaced."""

from coding_agent import session, state

from waxal_agent import agent as module
from waxal_agent.agent import AgentTurns, TOOLS, user_folder


def fake_send(reply):
    def send(text):
        ui = state.ui
        ui.assistant_start()
        ui.assistant_text("let me look. ")
        ui.assistant_end()
        ui.assistant_start()
        ui.assistant_text(reply + f" (asked: {text})")
        ui.assistant_end()
        return True
    return send


def test_a_turn_uses_the_persons_folder_the_read_only_tools_and_returns_the_last_reply(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "MEMORY_HOME", tmp_path / "memory")
    monkeypatch.setattr(session, "send", fake_send("The total is 642."))
    turns = AgentTurns(tmp_path / "users")
    reply, notes = turns.ask("+221 77 123", "what is the total?")
    assert reply == "The total is 642. (asked: what is the total?)" and notes == []
    assert state.tool_names == set(TOOLS) and "write_file" not in state.tool_names and "run_python" not in state.tool_names
    assert state.workspace == (tmp_path / "users" / "_221_77_123").resolve()
    assert state.system_prompt and "voice notes" in state.system_prompt


def test_each_person_has_a_separate_folder_and_names_cannot_escape(tmp_path):
    a, b = user_folder(tmp_path, "a"), user_folder(tmp_path, "b")
    assert a != b and a.parent == tmp_path
    for hostile in ("../../etc", "..", ".", "", "a/b", "C:\\Windows"):
        folder = user_folder(tmp_path, hostile)
        assert folder.parent == tmp_path and folder.name not in ("", ".", "..")


def test_questions_are_refused_and_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "MEMORY_HOME", tmp_path / "memory")

    def send(text):
        assert state.ui.confirm("Delete costs.xlsx?") == "no"
        state.ui.error("Claude is unreachable")
        return False
    monkeypatch.setattr(session, "send", send)
    reply, notes = AgentTurns(tmp_path / "users").ask("u", "delete it")
    assert reply == "" and "Claude is unreachable" in notes and any("Delete costs.xlsx?" in n for n in notes)


def test_a_missing_claude_setup_becomes_a_note_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "MEMORY_HOME", tmp_path / "memory")

    def send(text):
        raise KeyError("ANTHROPIC_FOUNDRY_ENDPOINT")
    monkeypatch.setattr(session, "send", send)
    reply, notes = AgentTurns(tmp_path / "users").ask("u", "hello")
    assert reply == "" and any("ANTHROPIC_API_KEY" in n for n in notes)
