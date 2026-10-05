import json

import pytest

from waxal_agent import files as files_module
from waxal_agent.drive_sync import MANIFEST, DriveError, DriveSync
from waxal_agent.files import Library

PDF, DOC, SHEET = "application/pdf", "application/vnd.google-apps.document", "application/vnd.google-apps.spreadsheet"


class Response:
    def __init__(self, status=200, payload=None, content=b"", text=""):
        self.status_code, self._payload, self.content, self.text = status, payload, content, text

    def json(self):
        return self._payload


class FakeDrive:
    """A Google Drive folder: files by id; serves the listing, downloads and exports like the real API."""

    def __init__(self):
        self.files, self.calls, self.fail_listing = {}, [], False

    def put(self, id, name, mime=PDF, content=b"data", modified="2026-01-01T00:00:00Z", size=None):
        self.files[id] = {"id": id, "name": name, "mimeType": mime, "modifiedTime": modified, "size": str(size or len(content)),
                          "content": content}

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        path = url.split("/drive/v3/")[1]
        if path == "files":
            if self.fail_listing:
                return Response(403, text="The caller does not have permission")
            page = [{k: v for k, v in f.items() if k != "content"} for f in self.files.values()]
            return Response(payload={"files": page})
        if path.endswith("/export"):
            file = self.files[path.split("/")[1]]
            return Response(content=b"EXPORT:" + params["mimeType"].encode() + b":" + file["content"])
        return Response(content=self.files[path.split("/")[1]]["content"])


@pytest.fixture
def setup(tmp_path):
    drive = FakeDrive()
    library = Library(tmp_path / "documents")
    return drive, library, DriveSync(library, "FOLDER", session=drive)


def names(library):
    return [f["name"] for f in library.list()]


def test_new_files_are_added_and_google_documents_are_exported(setup):
    drive, library, sync = setup
    drive.put("1", "Code CIMA.pdf", content=b"pdf")
    drive.put("2", "Notes", DOC, b"doc")
    drive.put("3", "Costs", SHEET, b"sheet")
    result = sync.sync_once()
    assert result["added"] == 3 and result["skipped"] == []
    assert names(library) == ["Code CIMA.pdf", "Costs.xlsx", "Notes.pdf"]
    assert (library.folder / "Notes.pdf").read_bytes() == b"EXPORT:application/pdf:doc"
    assert (library.folder / "Costs.xlsx").read_bytes().startswith(b"EXPORT:application/vnd.openxmlformats")
    assert (library.folder / "Code CIMA.pdf").read_bytes() == b"pdf"
    assert not list(library.folder.glob(".part-*"))                                 # no half-written file is left


def test_a_change_replaces_the_file_and_nothing_is_downloaded_again_when_unchanged(setup):
    drive, library, sync = setup
    drive.put("1", "Code.pdf", content=b"v1")
    sync.sync_once()
    drive.calls.clear()
    assert sync.sync_once() == {"added": 0, "updated": 0, "removed": 0, "skipped": []}
    assert not [c for c in drive.calls if "alt" in c[1]]                            # only the listing
    drive.put("1", "Code.pdf", content=b"v2", modified="2026-02-01T00:00:00Z")
    assert sync.sync_once()["updated"] == 1 and (library.folder / "Code.pdf").read_bytes() == b"v2"
    assert names(library) == ["Code.pdf"]                                           # replaced, not "Code (2).pdf"


def test_a_file_removed_or_renamed_in_drive_goes_locally(setup):
    drive, library, sync = setup
    drive.put("1", "Old.pdf")
    drive.put("2", "Keep.pdf")
    sync.sync_once()
    del drive.files["1"]
    drive.files["2"]["name"] = "Renamed.pdf"
    result = sync.sync_once()
    assert result["removed"] == 1 and names(library) == ["Renamed.pdf"]


def test_files_the_sync_did_not_add_are_never_touched_or_overwritten(setup):
    drive, library, sync = setup
    library.save("Manual.pdf", b"mine")
    drive.put("abcdef123", "Manual.pdf", content=b"from drive")
    sync.sync_once()
    assert (library.folder / "Manual.pdf").read_bytes() == b"mine"                  # the manual file is untouched
    assert (library.folder / "Manual (abcdef).pdf").read_bytes() == b"from drive"
    drive.files.clear()
    sync.sync_once()
    assert names(library) == ["Manual.pdf"]                                         # only what the sync added is removed


def test_unusable_and_oversized_files_are_skipped_with_the_reason(setup, monkeypatch):
    drive, library, sync = setup
    monkeypatch.setattr(files_module, "MAX_BYTES", 10)
    drive.put("1", "program.exe", "application/octet-stream")
    drive.put("2", "Big.pdf", size=11)
    drive.put("3", "Fine.pdf", content=b"ok")
    result = sync.sync_once()
    assert names(library) == ["Fine.pdf"] and result["added"] == 1
    assert any("program.exe" in s for s in result["skipped"]) and any("too big" in s for s in result["skipped"])


def test_a_failed_listing_changes_nothing_and_is_reported(setup):
    drive, library, sync = setup
    drive.put("1", "Code.pdf")
    sync.sync_once()
    drive.fail_listing = True
    with pytest.raises(DriveError, match="HTTP 403"):
        sync.sync_once()
    assert names(library) == ["Code.pdf"] and "HTTP 403" in sync.status()["error"]
    drive.fail_listing = False
    sync.sync_once()
    assert sync.status()["error"] == "" and sync.status()["files"] == 1


def test_the_manifest_is_a_hidden_file_and_the_library_does_not_list_it(setup):
    drive, library, sync = setup
    drive.put("1", "Code.pdf")
    sync.sync_once()
    assert json.loads((library.folder / MANIFEST).read_text())["1"]["name"] == "Code.pdf" and names(library) == ["Code.pdf"]


def test_a_missing_key_is_explained(monkeypatch, tmp_path):
    monkeypatch.delenv("WAXAL_DRIVE_CREDENTIALS", raising=False)
    monkeypatch.delenv("WAXAL_DRIVE_CREDENTIALS_JSON", raising=False)
    with pytest.raises(DriveError, match="service account key"):
        DriveSync(Library(tmp_path), "F").session
    monkeypatch.setenv("WAXAL_DRIVE_CREDENTIALS", str(tmp_path / "missing.json"))
    with pytest.raises(DriveError, match="cannot be read"):
        DriveSync(Library(tmp_path), "F").session
