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


def test_there_is_no_speak_wolof_tool_the_final_reply_is_the_answer():
    from coding_agent.tools import TOOL_HANDLERS
    from waxal_agent.agent import TOOLS as WAXAL_TOOLS, spoken_reply
    assert "speak_wolof" not in WAXAL_TOOLS and "speak_wolof" not in TOOL_HANDLERS
    assert spoken_reply("My answer.", []) == "My answer."                          # the final reply
    assert spoken_reply("x", ["Quel fichier ?"]) == "Quel fichier ?"               # a question comes first


def test_ask_human_tells_the_agent_to_end_its_turn():
    from waxal_agent import voice_ui
    ui = voice_ui.VoiceUI()
    ui.panel("Ban fichier?", tone="question")
    assert ui.questions == ["Ban fichier?"] and "finish your turn" in ui.ask_text("Your answer: ")


def test_the_agent_is_told_to_answer_only_from_the_library_documents():
    from waxal_agent.agent import CONCISE, SYSTEM_PROMPT
    assert "only from information you found in the documents of the library" in SYSTEM_PROMPT and "Never use outside knowledge" in SYSTEM_PROMPT
    assert "answer only from what you found in the library documents" in CONCISE


def test_stop_only_reaches_a_running_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "MEMORY_HOME", tmp_path / "memory")
    turns = AgentTurns(tmp_path / "users")
    stops = []
    monkeypatch.setattr(session, "stop", lambda: stops.append(1))
    assert turns.stop() is False and stops == []              # nothing running: a stale stop must not abort the next turn

    def send(text):
        assert turns.stop() is True and stops == [1]          # asked from another thread while the turn runs
        return True
    monkeypatch.setattr(session, "send", send)
    turns.ask("u", "hello")
    assert turns.stop() is False                              # the turn is over


def test_a_stop_asked_before_a_turn_does_not_abort_it(tmp_path, monkeypatch):
    from coding_agent import state
    monkeypatch.setattr(session, "MEMORY_HOME", tmp_path / "memory")
    state.stop_requested = True
    seen = []
    monkeypatch.setattr(session, "send", lambda text: seen.append(state.stop_requested) or True)
    AgentTurns(tmp_path / "users").ask("u", "hello")
    assert seen == [False]


def test_the_shared_library_is_a_read_only_folder_and_the_prompt_says_where_it_is(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "MEMORY_HOME", tmp_path / "memory")
    library = tmp_path / "library"
    added, seen = [], []
    monkeypatch.setattr(session, "add_read_folder", lambda path: added.append(path))
    monkeypatch.setattr(session, "send", lambda text: seen.append(state.system_prompt) or True)
    AgentTurns(tmp_path / "users", documents=library).ask("221771234567", "what is the total?")
    assert added == [library.resolve()] and library.is_dir()                       # created, and granted for reading only
    assert library.resolve().as_posix() in seen[0] and "{documents}" not in seen[0]
    assert (tmp_path / "users" / "221771234567").is_dir()                          # the person's own folder holds only their conversation


def test_the_style_guide_is_part_of_the_prompt_only_when_the_agent_writes_the_wolof(tmp_path, monkeypatch):
    style = tmp_path / "translation_style_prompt.md"
    style.write_text("Write *jàmm*.", encoding="utf-8")
    monkeypatch.setenv("WAXAL_TRANSLATION_STYLE", str(style))
    turns = AgentTurns(tmp_path / "users")
    assert turns.prompt_for_turn() == turns.system_prompt                       # English: the translator uses the guide, not the agent
    monkeypatch.setattr(module, "REPLY_LANGUAGE", "wo")
    assert turns.prompt_for_turn().startswith(turns.system_prompt) and "Write *jàmm*." in turns.prompt_for_turn()
    style.write_text("Say *jërejëf*.", encoding="utf-8")                        # read at every turn
    assert "jërejëf" in turns.prompt_for_turn() and "jàmm" not in turns.prompt_for_turn()


def test_the_prompt_says_what_really_happens_to_the_text():
    import subprocess
    import sys
    code = "from waxal_agent import agent; print(agent.SPOKEN); print(agent.SYSTEM_PROMPT.count('machine'))"
    for language, spoken, machine in (("en", "translated into Wolof by a machine", "1"), ("wo", "exactly as you write it", "0")):
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             env={**__import__("os").environ, "WAXAL_REPLY_LANGUAGE": language}).stdout
        assert spoken in out and out.strip().endswith(machine), out


def test_the_instructions_are_a_separate_read_only_folder_the_agent_discovers_itself(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "MEMORY_HOME", tmp_path / "memory")
    monkeypatch.setattr(session, "send", fake_send("ok"))
    (tmp_path / "instructions").mkdir()
    (tmp_path / "instructions" / "INSTRUCTIONS.md").write_text("Be kind.")
    turns = AgentTurns(tmp_path / "users", documents=tmp_path / "library", instructions=tmp_path / "instructions")
    prompt = turns.system_prompt
    assert "INSTRUCTIONS.md" in prompt and "read_file" in prompt and "{instructions" not in prompt and "{documents}" not in prompt
    assert "follow whatever they say" in prompt and "they win" in prompt                    # the owner's instructions beat the other rules
    assert "unless your own instructions" in CONCISE
    assert (tmp_path / "instructions").resolve().as_posix() in prompt and (tmp_path / "library").resolve().as_posix() in prompt
    turns.ask("u", "hello")
    roots = {r.resolve() for r in state.read_roots}
    assert roots == {(tmp_path / "library").resolve(), (tmp_path / "instructions").resolve()}   # two folders, and never data/ itself
    assert "read_file" in module.TOOLS


def test_without_an_instructions_folder_the_prompt_does_not_mention_one(tmp_path):
    assert "INSTRUCTIONS.md" not in AgentTurns(tmp_path / "users", documents=tmp_path / "library").system_prompt


def run_responses(ui, responses):
    """Play what CodeAgent's loop calls on the UI: per response, its text, and the tools it starts."""
    for text, tools in responses:
        ui.assistant_start()
        ui.assistant_text(text)
        for name in tools:
            ui.tool_start(name)
        ui.assistant_end()


def test_the_answer_written_before_share_link_is_not_lost_when_the_agent_ends_with_a_short_sentence():
    from waxal_agent.voice_ui import VoiceUI
    ui = VoiceUI()
    run_responses(ui, [("Le code ne rend pas l'assurance obligatoire. Je vous conseille notre partenaire.", ["share_link"]),
                       ("Voici le lien pour les contacter.", [])])
    assert ui.reply == "Le code ne rend pas l'assurance obligatoire. Je vous conseille notre partenaire. Voici le lien pour les contacter."


def test_narration_before_other_tools_is_still_dropped():
    from waxal_agent.voice_ui import VoiceUI
    ui = VoiceUI()
    run_responses(ui, [("Let me look in the documents.", ["read_pdf"]), ("Je cherche l'article.", ["read_pdf"]), ("La réponse complète.", [])])
    assert ui.reply == "La réponse complète."


def test_an_answer_that_shares_a_link_and_ends_the_turn_is_spoken_whole():
    from waxal_agent.voice_ui import VoiceUI
    ui = VoiceUI()
    run_responses(ui, [("Je cherche.", ["read_pdf"]), ("Voici ma réponse, et le lien.", ["share_link"])])
    assert ui.reply == "Voici ma réponse, et le lien."
    assert "write it now, in full" in ui.share({"url": "https://renassur.sn/", "label": "Renassur"})
