"""The library, fed from a Google Drive folder: the administrators add, replace and remove documents in Drive and the server
mirrors that folder into the local library (data/documents) that the agent reads.

    WAXAL_DRIVE_FOLDER            the folder id (the last part of the folder's address in Drive)
    WAXAL_DRIVE_CREDENTIALS       path of a service account's JSON key file   (or WAXAL_DRIVE_CREDENTIALS_JSON: the JSON itself)
    WAXAL_DRIVE_INTERVAL          seconds between two syncs (default 600)

Share the folder with the service account's e-mail address (viewer is enough). Only the files directly in the folder are used
(subfolders are ignored). Every file is copied as it is (whatever its kind); a file over
WAXAL_MAX_UPLOAD_MB is skipped and logged. A change in Drive replaces the local file; a file removed or
trashed in Drive is removed locally. Files that were not put there by the sync are never touched. A failed listing changes nothing.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path

from . import files as files_module
from .files import FileRefused, Library

log = logging.getLogger("waxal.drive")

API = "https://www.googleapis.com/drive/v3"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER = "application/vnd.google-apps.folder"
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


class DriveSync:
    def __init__(self, library: Library, folder_id: str, session=None, interval: float | None = None) -> None:
        self.library, self.folder_id, self._session = library, folder_id, session
        self.interval = interval if interval is not None else float(os.environ.get("WAXAL_DRIVE_INTERVAL") or 600)
        self._lock = threading.Lock()

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
        found, token = [], None
        query = f"'{self.folder_id.replace(chr(39), '')}' in parents and trashed = false"
        while True:
            params = {"q": query, "pageSize": 100, "includeItemsFromAllDrives": "true",
                      "fields": "nextPageToken, files(id, name, mimeType, modifiedTime, size)"}
            if token:
                params["pageToken"] = token
            data = self._get("files", **params).json()
            found += [f for f in data.get("files", []) if f.get("mimeType") != FOLDER]
            token = data.get("nextPageToken")
            if not token:
                return found

    def _content(self, item: dict) -> bytes:
        return self._get(f"files/{item['id']}", alt="media").content

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
        """The file name as it is (any kind of file is copied), made safe as a name: never a path."""
        name = re.sub(r"[^\w.()\- ]", "_", item["name"].replace("\\", "/").rsplit("/", 1)[-1]).strip(". ")[-120:]
        if not name:
            raise FileRefused("no usable name")
        return name

    def sync_once(self) -> dict:
        """Mirror the Drive folder now. Returns {"added", "updated", "removed", "skipped": [...]}; raises DriveError when the folder
        cannot be listed (nothing is changed then)."""
        with self._lock:
            try:
                items = self.listing()
            except DriveError as e:
                log.error("Google Drive sync failed: %s", e)
                raise
            manifest, result = self._manifest(), {"added": 0, "updated": 0, "removed": 0, "skipped": []}
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
                (self.library.folder / manifest.pop(drive_id)["name"]).unlink(missing_ok=True)
                result["removed"] += 1
            self._save_manifest(manifest)
            log.info("Google Drive sync: %s added, %s updated, %s removed, %s skipped", result["added"], result["updated"],
                     result["removed"], len(result["skipped"]))
            return result

    def _sync_item(self, item: dict, manifest: dict, taken: dict, result: dict) -> None:
        name = self.local_name(item)
        if int(item.get("size") or 0) > files_module.MAX_BYTES:
            raise FileRefused(f"too big (at most {files_module.MAX_BYTES // (1024 * 1024)} MB)")
        known = manifest.get(item["id"])
        if known and known["name"] != name:  # renamed in Drive: the old local file goes, the new one is downloaded
            (self.library.folder / known["name"]).unlink(missing_ok=True)
            taken.pop(known["name"], None)
        elif known and known["modified"] == item["modifiedTime"] and (self.library.folder / name).is_file():
            return                                                                  # unchanged
        # The name is already used by another Drive file, or by a file the sync did not put there (never overwritten): add a code.
        if taken.get(name, item["id"]) != item["id"] or ((self.library.folder / name).exists() and name not in taken):
            name = f"{Path(name).stem} ({item['id'][:6]}){Path(name).suffix}"
        data = self._content(item)
        if not data:
            raise FileRefused("empty")
        if len(data) > files_module.MAX_BYTES:
            raise FileRefused("too big")
        target = self.library.folder / name
        temporary = self.library.folder / f".part-{item['id']}"                      # the agent never sees a half-written file
        temporary.write_bytes(data)
        os.replace(temporary, target)
        result["updated" if (item["id"] in manifest) else "added"] += 1
        manifest[item["id"]] = {"name": name, "modified": item["modifiedTime"]}
        taken[name] = item["id"]

    def start(self) -> threading.Thread:
        """Sync now and then every `interval` seconds, in a background thread (a failure is logged, the next run tries again)."""
        stop = threading.Event()

        def loop() -> None:
            while True:
                try:
                    self.sync_once()
                except Exception as e:  # never let the thread die: Drive may be down for a while (sync_once logged why)
                    log.debug("sync failed: %s", e)
                if stop.wait(self.interval):
                    return
        thread = threading.Thread(target=loop, name="drive-sync", daemon=True)
        thread.stop = stop.set  # type: ignore[attr-defined]
        thread.start()
        return thread
