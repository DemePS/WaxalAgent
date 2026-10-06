from pathlib import Path

from coding_agent import session, skills as coding_skills, state
from coding_agent.skills import discover_skills, read_skill_header, skill_problems, skills_catalog, tool_load_skill

from tests.test_agent import fake_send
from waxal_agent import agent as module
from waxal_agent.agent import AgentTurns, TOOLS

EXAMPLES = Path(__file__).resolve().parent.parent / "docs" / "skills"


def test_the_two_example_skills_are_valid_skills():
    assert skill_problems(EXAMPLES) == []
    for name in ("recommend-partner-insurance", "register-on-partner-website"):
        header = read_skill_header(EXAMPLES / name / "SKILL.md")
        assert header["name"] == name and len(header["description"]) > 40


def test_the_agent_gets_load_skill_and_only_the_skills_of_its_own_folder(tmp_path, monkeypatch):
    assert "load_skill" in TOOLS
    skills = tmp_path / "skills" / "greet"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("---\nname: greet\ndescription: Use to say hello.\n---\nSay salam.\n")
    monkeypatch.setattr(session, "MEMORY_HOME", tmp_path / "memory")
    monkeypatch.setattr(session, "send", fake_send("ok"))
    turns = AgentTurns(tmp_path / "users", skills=tmp_path / "skills")
    turns.ask("u", "hello")
    assert sorted(state.skills) == ["greet"]                                  # not CodeAgent's coding skills
    assert "greet: Use to say hello." in skills_catalog() and "ai-engineer" not in skills_catalog()
    assert "Say salam." in tool_load_skill("greet")
    assert "load_skill" in turns.system_prompt


def test_a_skill_added_while_the_server_runs_is_found_at_the_next_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "MEMORY_HOME", tmp_path / "memory")
    monkeypatch.setattr(session, "send", fake_send("ok"))
    turns = AgentTurns(tmp_path / "users", skills=tmp_path / "skills")
    turns.ask("u", "one")
    assert state.skills == {}
    (tmp_path / "skills" / "late").mkdir()
    (tmp_path / "skills" / "late" / "SKILL.md").write_text("---\ndescription: Use late.\n---\nbody")
    turns.ask("u", "two")
    assert list(state.skills) == ["late"]


def test_without_a_skills_folder_the_prompt_does_not_mention_skills(tmp_path):
    assert "load_skill" not in AgentTurns(tmp_path / "users").system_prompt


def test_the_copy_of_the_example_skills_into_data_skills_is_documented():
    readme = (EXAMPLES.parent.parent / "README.md").read_text(encoding="utf-8")
    assert "data/skills" in readme and "docs/skills" in readme
