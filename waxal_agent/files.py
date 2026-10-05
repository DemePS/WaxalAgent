"""The library: the documents shared by every person (data/documents, WAXAL_DOCUMENTS). An administrator adds them (the test
page, or a document/photo sent on WhatsApp from a WAXAL_ADMINS number); the agent reads them for everybody. Only kinds of file the
agent's read-only tools can use are accepted."""

import os
import re
from pathlib import Path

ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".xlsx", ".xlsm", ".csv", ".txt", ".md", ".json"}
MAX_BYTES = int(float(os.environ.get("WAXAL_MAX_UPLOAD_MB") or 20) * 1024 * 1024)
MAX_FILES = 1000


class FileRefused(ValueError):
    """The file is not accepted (the message can be shown to the person)."""


def safe_name(name: str) -> str:
    """The file name alone (never a path), plain characters, an accepted extension."""
    name = (name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    name = re.sub(r"[^\w.()\- ]", "_", name).lstrip(". ")[-120:]
    if not name or Path(name).suffix.lower() not in ALLOWED:
        raise FileRefused("This kind of file cannot be used. Send a PDF, an image, an Excel file, or a text file.")
    return name


class Library:
    def __init__(self, folder: Path | str = "data/documents") -> None:
        self.folder = Path(folder).resolve()
        self.folder.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[dict]:
        files = [p for p in self.folder.iterdir() if p.is_file() and not p.name.startswith(".")]
        return [{"name": p.name, "size": p.stat().st_size} for p in sorted(files, key=lambda p: p.name.lower())]

    def save(self, name: str, data: bytes) -> str:
        name = safe_name(name)
        if not data:
            raise FileRefused("The file is empty.")
        if len(data) > MAX_BYTES:
            raise FileRefused(f"The file is too big (at most {MAX_BYTES // (1024 * 1024)} MB).")
        if len(self.list()) >= MAX_FILES:
            raise FileRefused("Too many files: delete some first.")
        target, stem, suffix, n = self.folder / name, Path(name).stem, Path(name).suffix, 1
        while target.exists():  # never overwrite: "report (2).pdf"
            n += 1
            target = self.folder / f"{stem} ({n}){suffix}"
        target.write_bytes(data)
        return target.name

    def delete(self, name: str) -> None:
        target = self.folder / safe_name(name)
        if not target.is_file():
            raise FileRefused("No such file.")
        target.unlink()
