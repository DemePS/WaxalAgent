"""The cookie-cutter: a generated app is complete, has no placeholder left, and its command and tests fit the library."""

import importlib.util
import re
import sys
import tomllib
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "cookie-cutter" / "new_app.py"
spec = importlib.util.spec_from_file_location("new_app", SCRIPT)
new_app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(new_app)


def make(tmp_path, *argv):
    out = tmp_path / "myapp"
    assert new_app.main(["myapp", "--out", str(out), *argv]) == 0
    return out


def test_a_generated_app_has_its_files_and_no_placeholder_left(tmp_path):
    out = make(tmp_path, "--title", "My App", "--description", "An app for tests.", "--purpose", "Answer about tests.",
               "--language", "en", "--domains", "example.org=Example", "--brand", "#112233")
    files = {str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()}
    for needed in ("myapp/cli.py", "myapp/static/index.html", "pyproject.toml", "Dockerfile", "docker-compose.yml", "example.env",
                   "data/instructions/INSTRUCTIONS.md", "data/skills/answer-from-the-library/SKILL.md", "tests/test_app.py", "library/.gitkeep"):
        assert needed in files, needed
    for path in out.rglob("*"):
        if path.is_file():
            assert not re.search(r"\{\{[a-z_]+\}\}", path.read_text(encoding="utf-8")), path
    pyproject = tomllib.loads((out / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["name"] == "myapp" and pyproject["project"]["description"] == "An app for tests."
    assert pyproject["project"]["scripts"] == {"myapp": "myapp.cli:main"}
    page = (out / "myapp/static/index.html").read_text(encoding="utf-8")
    assert "<title>My App</title>" in page and '<html lang="en">' in page and "--accent:#112233;" in page
    assert "Answer about tests." in (out / "data/instructions/INSTRUCTIONS.md").read_text(encoding="utf-8")


def test_the_settings_follow_the_language_and_the_sites(tmp_path):
    out = make(tmp_path, "--language", "fr", "--domains", "a.org=A, b.org=B")
    env = (out / "example.env").read_text(encoding="utf-8")
    assert "\nWAXAL_TRANSLATION=off\n" in env and "\nWAXAL_REPLY_LANGUAGE=fr\n" in env and "\nWAXAL_LINK_DOMAINS=a.org=A, b.org=B\n" in env
    assert "A, B" in (out / "data/instructions/INSTRUCTIONS.md").read_text(encoding="utf-8")
    other = tmp_path / "other"
    assert new_app.main(["other", "--out", str(other), "--language", "wo"]) == 0
    env = (other / "example.env").read_text(encoding="utf-8")
    assert "\nWAXAL_TRANSLATION=off" not in env and "WAXAL_LINK_DOMAINS=" in env and "\nWAXAL_LINK_DOMAINS=" not in env  # Wolof, no sites


def test_a_bad_name_or_an_existing_folder_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        new_app.main(["My-App", "--out", str(tmp_path / "x")])
    make(tmp_path)
    with pytest.raises(SystemExit):
        new_app.main(["myapp", "--out", str(tmp_path / "myapp")])  # exists


def test_the_generated_command_starts_the_library_server(tmp_path, monkeypatch):
    out = make(tmp_path, "--title", "My App")
    monkeypatch.syspath_prepend(str(out))
    sys.modules.pop("myapp", None)
    sys.modules.pop("myapp.cli", None)
    import myapp.cli as cli  # noqa: PLC0415 -- the generated package
    seen = {}
    monkeypatch.setattr(cli, "serve", lambda **kw: seen.update(kw))
    cli.main()
    assert seen == {"prog": "myapp", "static_dir": cli.STATIC, "title": "My App"} and (cli.STATIC / "index.html").is_file()
