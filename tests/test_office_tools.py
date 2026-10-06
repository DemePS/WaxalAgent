import io
import zipfile
from types import SimpleNamespace

import pytest
from coding_agent import session, state
from coding_agent.tools import TOOL_HANDLERS, run_tool
from coding_agent.ui import UI

from waxal_agent import agent as agent_module  # registers the tools

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def docx(paragraphs, table=None) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    if table:
        body += "<w:tbl>" + "".join("<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in row) + "</w:tr>"
                                    for row in table) + "</w:tbl>"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>')
    return out.getvalue()


def pptx(slides: dict[int, list[str]]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for number, texts in slides.items():
            z.writestr(f"ppt/slides/slide{number}.xml", f'<p:sld xmlns:a="{A}" xmlns:p="p">'
                       + "".join(f"<a:p><a:r><a:t>{t}</a:t></a:r></a:p>" for t in texts) + "</p:sld>")
    return out.getvalue()


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(session, "MEMORY_HOME", tmp_path / "memory")
    user, library = tmp_path / "users" / "221771234567", tmp_path / "library"
    user.mkdir(parents=True)
    library.mkdir()
    session.open_project(user, ui=UI(), tools=agent_module.TOOLS)
    session.add_read_folder(library)
    return library


def call(name, **arguments):
    return run_tool(SimpleNamespace(id="t1", name=name, input=arguments))


def test_the_tools_are_registered_and_offered_to_the_agent():
    assert {"read_word", "read_powerpoint"} <= set(TOOL_HANDLERS) and "speak_wolof" not in TOOL_HANDLERS
    assert {"read_word", "read_powerpoint"} <= set(agent_module.TOOLS)


def test_a_word_file_is_read_as_paragraphs_and_table_rows(library):
    (library / "Policy.docx").write_bytes(docx(["Article 51", "", "The premium is due."], [["Item", "Amount"], ["Fire", "642"]]))
    result = call("read_word", path=(library / "Policy.docx").as_posix())
    assert result["content"] == "Article 51\nThe premium is due.\nItem | Amount\nFire | 642" and "is_error" not in result


def test_a_powerpoint_file_is_read_slide_by_slide_in_slide_order(library):
    (library / "Training.pptx").write_bytes(pptx({10: ["Last"], 2: ["Claims", "30 days"], 1: ["Welcome"]}))
    result = call("read_powerpoint", path=(library / "Training.pptx").as_posix())
    assert result["content"] == "--- slide 1 ---\nWelcome\n\n--- slide 2 ---\nClaims\n30 days\n\n--- slide 3 ---\nLast"


def test_old_formats_wrong_kinds_broken_and_missing_files_say_what_to_do(library):
    for name, data in (("old.doc", b"binary"), ("old.ppt", b"binary"), ("note.txt", b"text"), ("broken.docx", b"not a zip"), ("empty.docx", docx([]))):
        (library / name).write_bytes(data)
    word = lambda n: call("read_word", path=(library / n).as_posix())  # noqa: E731
    assert "old .doc file: save it as .docx" in word("old.doc")["content"] and word("old.doc")["is_error"]
    assert "not a .docx file" in word("note.txt")["content"]
    assert "not a valid .docx file" in word("broken.docx")["content"]
    assert word("empty.docx")["content"] == "(no text in this document)"
    assert "old .ppt file: save it as .pptx" in call("read_powerpoint", path=(library / "old.ppt").as_posix())["content"]
    assert "File not found" in word("missing.docx")["content"]


def test_the_same_rules_as_the_built_in_tools_decide_what_may_be_read(library, tmp_path):
    (tmp_path / "secret.docx").write_bytes(docx(["private"]))                         # outside the person's folder and the library
    result = call("read_word", path=(tmp_path / "secret.docx").as_posix())
    assert result["is_error"] and "private" not in result["content"]
