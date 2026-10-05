"""The agent's tools for Word and PowerPoint files (CodeAgent reads PDF, Excel, images and text, not these): read_word, read_powerpoint.

Registered with coding_agent.register_tool; a path is resolved with CodeAgent's own rules (the person's folder and the read-only library).
A .docx or .pptx is a zip of XML files, so the text is read with the standard library: no extra dependency.
"""

import re
import xml.etree.ElementTree as ET
import zipfile

from coding_agent import register_tool
from coding_agent.common import ToolError, resolve_readable, truncate

WORD = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DRAWING = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _archive(path: str, extension: str, old: str) -> zipfile.ZipFile:
    p = resolve_readable(path)
    if not p.is_file():
        raise ToolError(f"File not found: {path}")
    if p.suffix.lower() == old:
        raise ToolError(f"{path} is an old {old} file: save it as {extension} (or PDF) first.")
    if p.suffix.lower() != extension:
        raise ToolError(f"{path} is not a {extension} file.")
    try:
        return zipfile.ZipFile(p)
    except zipfile.BadZipFile:
        raise ToolError(f"{path} is not a valid {extension} file.")


def _words(element, tag: str) -> str:
    return "".join(t.text or "" for t in element.iter(f"{{{WORD}}}{tag}"))


def read_word(path: str) -> str:
    """The text of a Word (.docx) file: paragraphs in order, and table rows as "cell | cell"."""
    with _archive(path, ".docx", ".doc") as z:
        try:
            body = ET.fromstring(z.read("word/document.xml")).find(f"{{{WORD}}}body")
        except (KeyError, ET.ParseError):
            raise ToolError(f"{path} has no readable document text.")
    lines = []
    for block in body:
        if block.tag == f"{{{WORD}}}p":
            lines.append(_words(block, "t").strip())
        elif block.tag == f"{{{WORD}}}tbl":
            for row in block.iter(f"{{{WORD}}}tr"):
                lines.append(" | ".join(_words(cell, "t").strip() for cell in row.iter(f"{{{WORD}}}tc")))
    return truncate("\n".join(line for line in lines if line) or "(no text in this document)")


def read_powerpoint(path: str) -> str:
    """The text of a PowerPoint (.pptx) file, slide by slide."""
    with _archive(path, ".pptx", ".ppt") as z:
        names = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                       key=lambda n: int(re.search(r"(\d+)\.xml", n).group(1)))
        slides = []
        for number, name in enumerate(names, 1):
            try:
                root = ET.fromstring(z.read(name))
            except ET.ParseError:
                raise ToolError(f"{path}: slide {number} cannot be read.")
            lines = ["".join(t.text or "" for t in p.iter(f"{{{DRAWING}}}t")).strip() for p in root.iter(f"{{{DRAWING}}}p")]
            slides.append(f"--- slide {number} ---\n" + "\n".join(line for line in lines if line))
    return truncate("\n\n".join(slides) or "(no slides in this presentation)")


def _schema(name: str, kind: str) -> dict:
    return {"name": name, "description": f"Read the text of a {kind} file (not PDF, Excel or an image: they have their own tools).",
            "input_schema": {"type": "object", "properties": {"path": {"type": "string", "description": "Absolute path of the file."}},
                             "required": ["path"]}}


def register_office_tools() -> None:
    register_tool(_schema("read_word", "Word (.docx)"), read_word)
    register_tool(_schema("read_powerpoint", "PowerPoint (.pptx)"), read_powerpoint)
