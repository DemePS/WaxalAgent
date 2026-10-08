"""The core (waxal_agent) knows no web framework: a script, a queue worker or any other front end can use it. The web layer (waxal_server) sits on top."""

import ast
from pathlib import Path

CORE = Path(__file__).parent.parent / "waxal_agent"
WEB = {"fastapi", "starlette", "uvicorn", "waxal_server"}


def imported_roots(path: Path) -> set[str]:
    roots = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):  # imports inside functions count too
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_the_core_imports_no_web_framework_and_not_the_web_layer():
    offenders = {str(p.relative_to(CORE.parent)): sorted(imported_roots(p) & WEB) for p in CORE.rglob("*.py")}
    assert {name: found for name, found in offenders.items() if found} == {}


def test_the_core_has_no_web_page_and_no_command_line_of_the_server():
    assert not (CORE / "static").exists() and not (CORE / "server.py").exists() and not (CORE / "cli.py").exists()


def test_build_runtime_wires_the_core_without_any_web_framework(tmp_path, monkeypatch):
    from tests.test_pipeline import StubAgent
    from waxal_agent import certs, factory, maintenance
    from waxal_agent.mt.fake import FakeTranslator
    from waxal_agent.pipeline import Pipeline
    from waxal_agent.settings import Settings
    from waxal_agent.stt.fake import FakeListener
    from waxal_agent.tts.fake import FakeSpeaker
    monkeypatch.setattr(maintenance, "start", lambda enabled=True: None)
    monkeypatch.setattr(certs, "trust_system_certificates", lambda: None)
    monkeypatch.setattr(factory, "build_pipeline",
                        lambda settings, refresh=None: Pipeline(FakeListener(), FakeTranslator(), FakeSpeaker(), StubAgent()))
    settings = Settings.from_env({}).with_(documents=str(tmp_path / "docs"), data=str(tmp_path / "data"))
    said = []
    runtime = factory.build_runtime(settings, say=said.append)
    assert runtime.bot is None and runtime.s3 is None and runtime.files is not None
    assert runtime.pipeline.language == settings.language
    assert any(line.startswith("Engines:") for line in said)


def test_the_web_layer_ships_its_page():
    assert (Path(__file__).parent.parent / "waxal_server" / "static" / "index.html").is_file()
