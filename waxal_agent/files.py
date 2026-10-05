"""The person's files: what they upload (the test page, or a document/photo sent on WhatsApp) lands in their own folder,
the one the agent reads. Only kinds of file the agent's read-only tools can use are accepted."""

import os
import re
from pathlib import Path

from .agent import user_folder

ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".xlsx", ".xlsm", ".csv", ".txt", ".md", ".json"}
MAX_BYTES = int(float(os.environ.get("WAXAL_MAX_UPLOAD_MB") or 20) * 1024 * 1024)
MAX_FILES = 200


class FileRefused(ValueError):
    """The file is not accepted (the message can be shown to the person)."""


def safe_name(name: str) -> str:
    """The file name alone (never a path), plain characters, an accepted extension."""
    name = (name or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    name = re.sub(r"[^\w.()\- ]", "_", name).lstrip(". ")[-120:]
    if not name or Path(name).suffix.lower() not in ALLOWED:
        raise FileRefused("This kind of file cannot be used. Send a PDF, an image, an Excel file, or a text file.")
    return name


class UserFiles:
    def __init__(self, root: Path | str = "data/users") -> None:
        self.root = Path(root)

    def _folder(self, user_id: str) -> Path:
        return user_folder(self.root, user_id)

    def list(self, user_id: str) -> list[dict]:
        files = [p for p in self._folder(user_id).iterdir() if p.is_file() and not p.name.startswith(".")]
        return [{"name": p.name, "size": p.stat().st_size} for p in sorted(files, key=lambda p: p.name.lower())]

    def save(self, user_id: str, name: str, data: bytes) -> str:
        name = safe_name(name)
        if not data:
            raise FileRefused("The file is empty.")
        if len(data) > MAX_BYTES:
            raise FileRefused(f"The file is too big (at most {MAX_BYTES // (1024 * 1024)} MB).")
        folder = self._folder(user_id)
        if len(self.list(user_id)) >= MAX_FILES:
            raise FileRefused("Too many files: delete some first.")
        target, stem, suffix, n = folder / name, Path(name).stem, Path(name).suffix, 1
        while target.exists():  # never overwrite: "report (2).pdf"
            n += 1
            target = folder / f"{stem} ({n}){suffix}"
        target.write_bytes(data)
        return target.name

    def delete(self, user_id: str, name: str) -> None:
        target = self._folder(user_id) / safe_name(name)
        if not target.is_file():
            raise FileRefused("No such file.")
        target.unlink()
