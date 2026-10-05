"""The library, fed from a Google Drive folder: the administrators add, replace and remove documents in Drive and the server
mirrors that folder into the local library (data/documents) that the agent reads.

    WAXAL_DRIVE_FOLDER            the folder id (the last part of the folder's address in Drive)
    WAXAL_DRIVE_CREDENTIALS       path of a service account's JSON key file   (or WAXAL_DRIVE_CREDENTIALS_JSON: the JSON itself)
    WAXAL_DRIVE_INTERVAL          seconds between two syncs (default 600)

Share the folder with the service account's e-mail address (viewer is enough). Subfolders are mirrored as subfolders (up to 5 levels).
Google Docs and Slides become PDF, Google Sheets become xlsx, Word (.docx) and PowerPoint (.pptx) files become text files
("Report.docx.txt"); other files must be a kind the agent can read (PDF, image, Excel, CSV, text) and at most WAXAL_MAX_UPLOAD_MB.
A change in Drive replaces the local file; a file removed or trashed in Drive is removed locally. Files that were not put there by
the sync are never touched. A failed listing changes nothing, and a folder that suddenly looks empty removes nothing.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path

from . import files as files_module
from .files import FileRefused, Library, safe_name

log = logging.getLogger("waxal.drive")

API = "https://www.googleapis.com/drive/v3"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER = "application/vnd.google-apps.folder"
EXPORTS = {  # Google's own formats cannot be downloaded as they are: they are exported
    "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
}
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
MAX_DEPTH, MAX_FOLDERS = 5, 200
MANIFEST = ".drive-manifest.json"  # which local file came from which Drive file (kept in the library folder)


class DriveError(Exception):
    """Google Drive did not answer as expected (the message is for the operator)."""


def session_from_environment():
    """An authorised HTTP session for a service account (the key from WAXAL_DRIVE_CREDENTIALS / _JSON)."""
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account
    path, raw = os.environ.get("WAXAL_DRIVE_CREDENTIALS"), os.environ.get("WAXAL_DRIVE_CREDENTIALS_JSON")
    try:
        if raw:
            credentials = service_account.Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
        elif path:
            credentials = service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
        else:
            raise DriveError("Google Drive needs a service account key: set WAXAL_DRIVE_CREDENTIALS (a JSON file) or WAXAL_DRIVE_CREDENTIALS_JSON.")
    except (OSError, ValueError) as e:
        raise DriveError(f"The Google Drive credentials cannot be read: {e}") from e
    return AuthorizedSession(credentials)


def _text_of(xml: bytes, paragraph: str, text: str, ns: str) -> list[str]:
    root, lines = ET.fromstring(xml), []
    for p in root.iter(f"{{{ns}}}{paragraph}"):
        line = "".join(t.text or "" for t in p.iter(f"{{{ns}}}{text}")).strip()
        if line:
            lines.append(line)
    return lines


def docx_text(data: bytes) -> str:
    """The text of a Word file: paragraphs, and table rows as "cell | cell" (a .docx is a zip of XML: no extra library)."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with zipfile.ZipFile(BytesIO(data)) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    lines = []
    for block in root.find(f"{{{ns}}}body"):
        if block.tag == f"{{{ns}}}p":
            line = "".join(t.text or "" for t in block.iter(f"{{{ns}}}t")).strip()
            if line:
                lines.append(line)
        elif block.tag == f"{{{ns}}}tbl":
            for row in block.iter(f"{{{ns}}}tr"):
                cells = ["".join(t.text or "" for t in cell.iter(f"{{{ns}}}t")).strip() for cell in row.iter(f"{{{ns}}}tc")]
                lines.append(" | ".join(cells))
    return "\n".join(lines)


def pptx_text(data: bytes) -> str:
    """The text of a PowerPoint file, slide by slide."""
    ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
    with zipfile.ZipFile(BytesIO(data)) as z:
        slides = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                        key=lambda n: int(re.search(r"(\d+)\.xml", n).group(1)))
        parts = [f"Slide {number}\n" + "\n".join(_text_of(z.read(name), "p", "t", ns)) for number, name in enumerate(slides, 1)]
    return "\n\n".join(parts)


CONVERT = {DOCX: docx_text, PPTX: pptx_text}  # Office files the agent cannot read: kept as text next to the original name


def folder_name(name: str) -> str:
    return re.sub(r"[^\w.()\- ]", "_", name).strip(". ")[:80] or "folder"


class DriveSync:
    def __init__(self, library: Library, folder_id: str, session=None, interval: float | None = None) -> None:
        self.library, self.folder_id, self._session = library, folder_id, session
        self.interval = interval if interval is not None else float(os.environ.get("WAXAL_DRIVE_INTERVAL") or 600)
        self._lock = threading.Lock()
        self.last_sync: float | None = None
        self.last_result: dict = {}
        self.error = ""

    # --- Drive
    @property
    def session(self):
        if self._session is None:
            self._session = session_from_environment()
        return self._session

    def _get(self, path: str, **params):
        response = self.session.get(f"{API}/{path}", params={"supportsAllDrives": "true", **params}, timeout=120)
        if response.status_code != 200:
            raise DriveError(f"Google Drive refused {path.split('?')[0]} (HTTP {response.status_code}): {response.text[:300]}")
        return response

    def listing(self) -> list[dict]:
        """Every file of the folder and its subfolders; each item has "path": the names of the folders above it."""
        found, queue, seen = [], [(self.folder_id, [])], 0
        while queue:
            folder, path = queue.pop(0)
            seen += 1
            if seen > MAX_FOLDERS:
                raise DriveError(f"More than {MAX_FOLDERS} folders: nothing was changed.")
            for item in self._children(folder):
                if item.get("mimeType") == FOLDER:
                    if len(path) < MAX_DEPTH:
                        queue.append((item["id"], path + [folder_name(item["name"])]))
                else:
                    found.append({**item, "path": path})
        return found

    def _children(self, folder_id: str) -> list[dict]:
        children, token = [], None
        query = f"'{folder_id.replace(chr(39), '')}' in parents and trashed = false"
        while True:
            params = {"q": query, "pageSize": 100, "includeItemsFromAllDrives": "true",
                      "fields": "nextPageToken, files(id, name, mimeType, modifiedTime, size)"}
            if token:
                params["pageToken"] = token
            data = self._get("files", **params).json()
            children += data.get("files", [])
            token = data.get("nextPageToken")
            if not token:
                return children

    def _content(self, item: dict) -> bytes:
        if item["mimeType"] in EXPORTS:
            return self._get(f"files/{item['id']}/export", mimeType=EXPORTS[item["mimeType"]][0]).content
        content = self._get(f"files/{item['id']}", alt="media").content
        if item["mimeType"] in CONVERT:
            try:
                return CONVERT[item["mimeType"]](content).encode("utf-8")
            except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
                raise DriveError(f"cannot read this Office file ({type(e).__name__})") from e
        return content

    # --- the mirror
    def _manifest(self) -> dict:
        try:
            return json.loads((self.library.folder / MANIFEST).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_manifest(self, manifest: dict) -> None:
        target = self.library.folder / MANIFEST
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        os.replace(temporary, target)

    @staticmethod
    def local_name(item: dict) -> str:
        """The path inside the library: "Folder/Name.pdf" (Google formats get their extension, Word and PowerPoint become .txt)."""
        name = item["name"]
        extension = EXPORTS.get(item["mimeType"], ("", ""))[1]
        if extension and not name.lower().endswith(extension):
            name += extension
        if item["mimeType"] in CONVERT:
            name += ".txt"
        elif name.lower().endswith((".doc", ".ppt")):
            raise FileRefused("an old Word or PowerPoint format: save it as .docx or .pptx")
        return "/".join(item.get("path", []) + [safe_name(name)])  # FileRefused: a kind the agent cannot read

    def sync_once(self) -> dict:
        """Mirror the Drive folder now. Returns {"added", "updated", "removed", "skipped": [...]}; raises DriveError when the folder
        cannot be listed (nothing is changed then)."""
        with self._lock:
            try:
                items = self.listing()
            except DriveError as e:
                self.error = str(e)
                log.error("Google Drive sync failed: %s", e)
                raise
            manifest, result = self._manifest(), {"added": 0, "updated": 0, "removed": 0, "skipped": []}
            if not items and manifest:  # a folder that suddenly looks empty (access lost, folder replaced): remove nothing
                self.error = "The Google Drive folder looks empty: nothing was removed. If you emptied it on purpose, add a document or ask the administrator."
                log.error(self.error)
                raise DriveError(self.error)
            taken = {entry["name"]: drive_id for drive_id, entry in manifest.items()}
            seen = set()
            for item in items:
                seen.add(item["id"])
                try:
                    self._sync_item(item, manifest, taken, result)
                except (FileRefused, DriveError) as e:
                    result["skipped"].append(f"{item.get('name')}: {e}")
                    log.warning("Skipped %s: %s", item.get("name"), e)
            for drive_id in [i for i in manifest if i not in seen]:  # removed or trashed in Drive
                self._remove(manifest.pop(drive_id)["name"])
                result["removed"] += 1
            self._save_manifest(manifest)
            self.last_sync, self.last_result, self.error = time.time(), result, ""
            log.info("Google Drive sync: %s added, %s updated, %s removed, %s skipped", result["added"], result["updated"],
                     result["removed"], len(result["skipped"]))
            return result

    def _sync_item(self, item: dict, manifest: dict, taken: dict, result: dict) -> None:
        name = self.local_name(item)
        if int(item.get("size") or 0) > files_module.MAX_BYTES:
            raise FileRefused(f"too big (at most {files_module.MAX_BYTES // (1024 * 1024)} MB)")
        known = manifest.get(item["id"])
        if known and known["name"] != name:  # renamed or moved in Drive: the old local file goes, the new one is downloaded
            self._remove(known["name"])
            taken.pop(known["name"], None)
        elif known and known["modified"] == item["modifiedTime"] and (self.library.folder / name).is_file():
            return                                                                  # unchanged
        # The name is already used by another Drive file, or by a file the sync did not put there (never overwritten): add a code.
        if taken.get(name, item["id"]) != item["id"] or ((self.library.folder / name).exists() and name not in taken):
            path = Path(name)
            name = (path.parent / f"{path.stem} ({item['id'][:6]}){path.suffix}").as_posix()
        data = self._content(item)
        if not data:
            raise FileRefused("empty")
        if len(data) > files_module.MAX_BYTES:
            raise FileRefused("too big")
        target = self.library.folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.library.folder / f".part-{item['id']}"                      # the agent never sees a half-written file
        temporary.write_bytes(data)
        os.replace(temporary, target)
        result["updated" if (item["id"] in manifest) else "added"] += 1
        manifest[item["id"]] = {"name": name, "modified": item["modifiedTime"]}
        taken[name] = item["id"]

    def _remove(self, name: str) -> None:
        """Delete a mirrored file and the folders it leaves empty (never the library folder itself)."""
        target = self.library.folder / name
        target.unlink(missing_ok=True)
        parent = target.parent
        while parent != self.library.folder and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent

    def status(self) -> dict:
        return {"last_sync": self.last_sync, "error": self.error, "files": len(self._manifest()), "folder": self.folder_id}

    def start(self) -> threading.Thread:
        """Sync now and then every `interval` seconds, in a background thread (a failure is logged, the next run tries again)."""
        stop = threading.Event()

        def loop() -> None:
            while True:
                try:
                    self.sync_once()
                except Exception as e:  # never let the thread die: Drive may be down for a while
                    self.error = self.error or str(e)
                if stop.wait(self.interval):
                    return
        thread = threading.Thread(target=loop, name="drive-sync", daemon=True)
        thread.stop = stop.set  # type: ignore[attr-defined]
        thread.start()
        return thread
