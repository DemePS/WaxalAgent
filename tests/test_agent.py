"""AgentTurns on top of the real CodeAgent session, with the model call replaced."""

from coding_agent import session, state

from waxal_agent import agent as module
from waxal_agent.agent import AgentTurns, TOOLS, build_system_prompt, concise_notice, user_folder
from waxal_agent.language import Language

CONCISE = concise_notice(Language())


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


def test_a_question_to_the_person_is_an_ordinary_final_reply(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "MEMORY_HOME", tmp_path / "memory")

    def send(text):
        state.ui.assistant_start()
        state.ui.assistant_text("Which invoice do you mean: the March one or the April one?")
        state.ui.assistant_end()
        state.ui.response_end("end_turn")
        return True
    monkeypatch.setattr(session, "send", send)
    reply, notes = AgentTurns(tmp_path / "users").ask("u", "what is the total?")
    assert reply == "Which invoice do you mean: the March one or the April one?"
    assert notes == []                                         # a question is not a failure


def test_the_agent_has_no_ask_human_tool_and_is_told_to_answer_with_a_question():
    from waxal_agent.agent import TOOLS as WAXAL_TOOLS, build_system_prompt
    from waxal_agent.language import Language
    assert "ask_human" not in WAXAL_TOOLS and "ask_human" not in build_system_prompt(Language())


def test_there_is_no_speak_wolof_tool_the_final_reply_is_the_answer():
    from coding_agent.tools import TOOL_HANDLERS
    from waxal_agent.agent import TOOLS as WAXAL_TOOLS, spoken_reply
    assert "speak_wolof" not in WAXAL_TOOLS and "speak_wolof" not in TOOL_HANDLERS
    assert spoken_reply("My answer.") == "My answer."                              # the final reply


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


def test_the_instructions_are_appended_to_the_system_prompt_and_win(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "MEMORY_HOME", tmp_path / "memory")
    monkeypatch.setattr(session, "send", fake_send("ok"))
    (tmp_path / "instructions").mkdir()
    (tmp_path / "instructions" / "INSTRUCTIONS.md").write_text("Be kind.")
    turns = AgentTurns(tmp_path / "users", documents=tmp_path / "library", instructions=tmp_path / "instructions")
    prompt = turns.prompt_for_turn()
    assert "Be kind." in prompt and "{instructions" not in prompt and "{documents}" not in prompt
    assert "follow whatever they say" in prompt and "they win" in prompt                    # the owner's instructions beat the other rules
    assert "read_file" in prompt                                                            # still a tool for the library...
    assert "list the instructions folder" not in prompt.lower()                             # ...but the agent is not sent to find the file
    assert "appended to your system prompt" in CONCISE
    turns.ask("u", "hello")
    roots = {r.resolve() for r in state.read_roots}
    assert roots == {(tmp_path / "library").resolve()}   # the agent does not need to open the instructions, and never data/ itself


def test_the_instructions_files_are_read_again_at_every_turn_main_file_first(tmp_path):
    folder = tmp_path / "instructions"
    folder.mkdir()
    (folder / "a-extra.txt").write_text("Extra rule.")
    (folder / "INSTRUCTIONS.md").write_text("Main rule.")
    (folder / "image.png").write_bytes(b"\x89PNG")
    turns = AgentTurns(tmp_path / "users", documents=tmp_path / "library", instructions=folder)
    prompt = turns.prompt_for_turn()
    assert prompt.index("Main rule.") < prompt.index("Extra rule.") and "image.png" not in prompt
    (folder / "INSTRUCTIONS.md").write_text("Changed rule.")
    assert "Changed rule." in turns.prompt_for_turn() and "Main rule." not in turns.prompt_for_turn()


def test_without_instructions_the_prompt_has_no_instructions_section(tmp_path):
    assert "Instructions from the owner" not in AgentTurns(tmp_path / "users", documents=tmp_path / "library").prompt_for_turn()
    empty = tmp_path / "instructions"
    empty.mkdir()
    assert "Instructions from the owner" not in AgentTurns(tmp_path / "users", instructions=empty).prompt_for_turn()


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


def test_the_agent_timing_line_counts_the_tool_calls_and_the_first_output(caplog):
    import logging
    from waxal_agent.voice_ui import VoiceUI
    caplog.set_level(logging.INFO, logger="waxal.agent")
    ui = VoiceUI()
    ui.log_timing()
    assert "first output after never, 0 tool call(s)" in caplog.text
    ui.thinking()
    ui.tool_start("read_file")
    ui.tool_start("grep")
    caplog.clear()
    ui.log_timing()
    assert "first output after 0." in caplog.text and "2 tool call(s)" in caplog.text


def test_the_reply_does_not_wait_for_the_notes_to_be_saved_but_the_next_turn_does(tmp_path, monkeypatch):
    import threading
    import time
    monkeypatch.setattr(session, "MEMORY_HOME", tmp_path / "memory")
    monkeypatch.setattr(session, "send", fake_send("ok"))
    saving, finish, order = threading.Event(), threading.Event(), []
    monkeypatch.setattr(session, "close", lambda: (saving.set(), finish.wait(5), order.append("saved")))
    turns = AgentTurns(tmp_path / "users", documents=tmp_path / "library")
    reply, notes = turns.ask("u", "hello")                      # returns while the notes are still being saved
    assert "ok" in reply and saving.wait(2) and order == []
    second = threading.Thread(target=lambda: (turns.ask("u", "again"), order.append("second")))
    second.start()
    time.sleep(0.3)
    assert order == []                                          # the next turn waits for the notes
    finish.set()
    second.join(5)
    assert order[0] == "saved" and "second" in order            # (the second turn saves its own notes too)


def _response(ui, text, stop_reason, *tools):
    """One model response: its text blocks, the tools it calls, and why it stopped."""
    texts = text if isinstance(text, list) else [text]
    for block in texts:
        ui.assistant_start()
        ui.assistant_text(block)
    for name in tools:
        ui.tool_start(name)
    ui.assistant_end()
    ui.response_end(stop_reason)


def test_a_response_in_several_text_blocks_keeps_all_of_them():
    from waxal_agent.voice_ui import VoiceUI
    ui = VoiceUI()
    _response(ui, ["Selon l'article 28, ", "les actions se prescrivent par deux ans."], "end_turn")
    assert ui.reply == "Selon l'article 28, les actions se prescrivent par deux ans."


def test_only_the_response_that_ends_the_turn_is_the_answer(caplog):
    import logging
    from waxal_agent.voice_ui import VoiceUI
    ui = VoiceUI()
    with caplog.at_level(logging.INFO, logger="waxal.agent"):
        _response(ui, "Je vais lire cette zone.", "tool_use", "read_pdf")
        assert ui.reply == "" and not ui.finished  # a step is not an answer
        _response(ui, "Prévenez l'assureur sous cinq jours.", "end_turn")
    assert ui.reply == "Prévenez l'assureur sous cinq jours." and ui.finished
    assert "agent working (tool_use): Je vais lire cette zone." in caplog.text
    assert "Prévenez" not in caplog.text  # the answer itself is not logged here: the pipeline logs it once


def test_what_the_agent_wrote_before_sharing_a_link_is_part_of_the_answer():
    from waxal_agent.voice_ui import VoiceUI
    ui = VoiceUI()
    _response(ui, "Le délai est de deux ans.", "tool_use", "share_link")
    _response(ui, "Voici le lien.", "end_turn")
    assert ui.reply == "Le délai est de deux ans. Voici le lien."


def test_an_answer_cut_short_is_not_spoken_as_if_it_were_complete():
    from waxal_agent.voice_ui import VoiceUI
    ui = VoiceUI()
    _response(ui, "Le délai est de", "max_tokens")
    assert ui.reply == "" and not ui.finished
    assert any("cut short (max_tokens)" in e for e in ui.errors)


def test_a_comment_after_a_link_is_not_kept_and_a_link_answer_survives_later_steps():
    from waxal_agent.voice_ui import VoiceUI
    ui = VoiceUI()
    _response(ui, "Le délai est de deux ans.", "tool_use", "share_link")
    _response(ui, "", "tool_use", "share_link")
    _response(ui, "Je vérifie un dernier point.", "tool_use", "read_pdf")  # a comment while it works: not part of the answer
    _response(ui, "C'est confirmé.", "end_turn")
    assert ui.reply == "Le délai est de deux ans. C'est confirmé."


def test_an_answer_cut_short_after_a_link_keeps_only_what_came_with_the_link():
    from waxal_agent.voice_ui import VoiceUI
    ui = VoiceUI()
    _response(ui, "Le délai est de deux ans.", "tool_use", "share_link")
    _response(ui, "Et pour le reste, il fa", "max_tokens")
    assert ui.reply == "Le délai est de deux ans." and not ui.finished
    assert any("cut short (max_tokens)" in e for e in ui.errors)


def test_an_interrupted_stream_is_not_spoken_as_if_it_were_complete():
    from waxal_agent.voice_ui import VoiceUI
    ui = VoiceUI()
    ui.assistant_start()
    ui.assistant_text("Le délai est de de")
    ui.assistant_end()
    ui.response_end("interrupted")
    assert ui.reply == "" and not ui.finished
    assert any("cut short (interrupted)" in e for e in ui.errors)


def test_without_stop_reasons_the_last_non_empty_response_is_the_answer_as_before():
    from waxal_agent.voice_ui import VoiceUI
    ui = VoiceUI()                     # an older CodeAgent only calls assistant_end
    for text in ("Je cherche.", "Voici la réponse.", ""):
        ui.assistant_start()
        ui.assistant_text(text)
        ui.assistant_end()
    assert ui.reply == "Voici la réponse."


def test_a_turn_with_stop_reasons_that_never_ends_is_flagged_but_an_older_codeagent_is_not():
    from waxal_agent.voice_ui import VoiceUI
    modern = VoiceUI()
    _response(modern, "Je cherche.", "tool_use", "read_pdf")          # the step limit stops it here: no end_turn
    assert modern.knows_why_responses_stopped and not modern.finished
    older = VoiceUI()                                                 # assistant_end only: nothing says why a response stopped
    older.assistant_start(); older.assistant_text("Voici la réponse."); older.assistant_end()
    assert not older.knows_why_responses_stopped and older.reply == "Voici la réponse."


def test_a_response_that_never_reached_assistant_end_is_not_spoken():
    from waxal_agent.voice_ui import VoiceUI
    ui = VoiceUI()
    ui.assistant_start()
    ui.assistant_text("Le délai est de de")  # the stream stopped here: no assistant_end, no response_end
    assert ui.reply == "" and not ui.finished


def test_the_agent_finds_pages_with_search_library_only():
    from waxal_agent.agent import TOOLS as WAXAL_TOOLS, build_system_prompt
    from waxal_agent.language import Language
    assert "search_library" in WAXAL_TOOLS and "search_pdf" not in WAXAL_TOOLS
    prompt = build_system_prompt(Language())
    assert "search_library" in prompt and "search_pdf" not in prompt
