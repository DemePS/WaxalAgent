"""AgentTurns on top of the real CodeAgent session, with the model call replaced."""

from coding_agent import session, state

from waxal_agent import agent as module
from waxal_agent.agent import CONCISE, AgentTurns, TOOLS, user_folder


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
    assert reply == f"The total is 642. (asked: what is the total?\n\n{CONCISE})" and notes == []
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


def test_a_question_to_the_person_is_spoken_on_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "MEMORY_HOME", tmp_path / "memory")

    def send(text):
        from coding_agent.tools.interaction import tool_ask_human
        answer = tool_ask_human("Which invoice do you mean: the March one or the April one?")
        assert "next message" in answer                       # the agent is told to stop and wait for the next voice note
        state.ui.assistant_start()
        state.ui.assistant_text("I need one detail first.")
        state.ui.assistant_end()
        return True
    monkeypatch.setattr(session, "send", send)
    reply, notes = AgentTurns(tmp_path / "users").ask("u", "what is the total?")
    assert reply == "Which invoice do you mean: the March one or the April one?"
    assert notes == []                                         # a question is not a failure


def test_a_question_replaces_the_rest_of_the_reply():
    from waxal_agent.agent import spoken_reply
    assert spoken_reply("Let me check. Which one?", ["Which one?"]) == "Which one?"
    assert spoken_reply("", ["Which one?"]) == "Which one?" and spoken_reply("Done.", []) == "Done."


def test_speak_wolof_is_a_tool_and_what_it_gets_is_what_is_spoken():
    from coding_agent import schemas, state
    from coding_agent.tools import TOOL_HANDLERS
    from waxal_agent.agent import TOOLS as WAXAL_TOOLS, spoken_reply
    from waxal_agent.voice_ui import VoiceUI
    assert "speak_wolof" in WAXAL_TOOLS and any(t["name"] == "speak_wolof" for t in schemas.TOOLS)
    state.ui = VoiceUI()
    assert "finish your turn" in TOOL_HANDLERS["speak_wolof"](text="Il y a trois documents.")
    TOOL_HANDLERS["speak_wolof"](text="Il y a trois documents.")           # twice: spoken once
    assert state.ui.spoken == ["Il y a trois documents."]
    assert spoken_reply("chatter", [], state.ui.spoken) == "Il y a trois documents."   # not the agent's other text
    assert spoken_reply("My answer.", [], []) == "My answer."                          # no tool call: the final reply
    assert spoken_reply("x", ["Quel fichier ?"], ["Salut"]) == "Quel fichier ?"        # a question comes first


def test_with_wolof_as_the_reply_language_ask_human_speaks_the_question_itself(monkeypatch):
    from waxal_agent import voice_ui
    monkeypatch.setattr(voice_ui, "REPLY_LANGUAGE", "wo")
    ui = voice_ui.VoiceUI()
    ui.panel("Ban fichier?", tone="question")
    assert "finish your turn" in ui.ask_text("Your answer: ") and ui.spoken == ["Ban fichier?"]
