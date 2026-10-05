import pytest
from fastapi.testclient import TestClient

from tests.test_pipeline import StubAgent
from tests.test_server import client as plain_client
from tests.test_whatsapp import Meta, make_bot, payload
from waxal_agent import files as files_module
from waxal_agent.files import FileRefused, UserFiles, safe_name
from waxal_agent.mt.fake import FakeTranslator
from waxal_agent.pipeline import Pipeline
from waxal_agent.server import create_app
from waxal_agent.stt.fake import FakeListener
from waxal_agent.tts.fake import FakeSpeaker


def test_names_are_plain_and_only_usable_kinds_are_accepted():
    assert safe_name("../../etc/passwd.pdf") == "passwd.pdf" and safe_name("C:\\docs\\Code CIMA 2019.PDF") == "Code CIMA 2019.PDF"
    assert safe_name(".hidden.txt") == "hidden.txt" and safe_name("a<b>:c.txt") == "a_b__c.txt"
    for bad in ("run.exe", "noextension", "", "archive.zip", "..", "script.py"):
        with pytest.raises(FileRefused):
            safe_name(bad)


def test_files_are_saved_listed_never_overwritten_and_deleted(tmp_path):
    store = UserFiles(tmp_path)
    assert store.save("+221 77", "code.pdf", b"one") == "code.pdf"
    assert store.save("+221 77", "code.pdf", b"two") == "code (2).pdf"            # never overwritten
    assert [f["name"] for f in store.list("+221 77")] == ["code (2).pdf", "code.pdf"]
    assert store.list("someone else") == []                                       # each person has their own folder
    store.delete("+221 77", "code.pdf")
    assert [f["name"] for f in store.list("+221 77")] == ["code (2).pdf"]
    with pytest.raises(FileRefused, match="No such file"):
        store.delete("+221 77", "code.pdf")


def test_empty_big_and_too_many_files_are_refused(tmp_path, monkeypatch):
    store = UserFiles(tmp_path)
    with pytest.raises(FileRefused, match="empty"):
        store.save("u", "a.txt", b"")
    monkeypatch.setattr(files_module, "MAX_BYTES", 10)
    with pytest.raises(FileRefused, match="too big"):
        store.save("u", "a.txt", b"x" * 11)
    monkeypatch.setattr(files_module, "MAX_FILES", 1)
    store.save("u", "a.txt", b"x")
    with pytest.raises(FileRefused, match="Too many"):
        store.save("u", "b.txt", b"x")


def app_client(tmp_path, token=None):
    pipeline = Pipeline(FakeListener(default="naka"), FakeTranslator(), FakeSpeaker(), StubAgent())
    return TestClient(create_app(pipeline, token, files=UserFiles(tmp_path)))


def test_the_page_can_upload_list_and_delete(tmp_path):
    c = app_client(tmp_path)
    assert c.get("/api/files").json() == {"files": [], "enabled": True}
    r = c.post("/api/files", params={"name": "invoice.pdf"}, content=b"%PDF-1.4")
    assert r.status_code == 200 and r.json()["name"] == "invoice.pdf" and r.json()["files"] == [{"name": "invoice.pdf", "size": 8}]
    assert (tmp_path / "test" / "invoice.pdf").read_bytes() == b"%PDF-1.4"        # in the folder the agent reads
    assert c.post("/api/files", params={"name": "virus.exe"}, content=b"x").status_code == 400
    assert c.post("/api/files", params={"name": "a.pdf"}, content=b"").status_code == 400
    assert c.delete("/api/files", params={"name": "invoice.pdf"}).json()["files"] == []


def test_uploads_need_the_token_and_the_page_hides_the_picker_when_disabled(tmp_path):
    c = app_client(tmp_path, token="s3cret")
    assert c.post("/api/files", params={"name": "a.pdf"}, content=b"x").status_code == 403
    assert c.get("/api/files").status_code == 403
    assert c.post("/api/files", params={"name": "a.pdf"}, content=b"x", headers={"x-token": "s3cret"}).status_code == 200
    off = plain_client()
    assert off.get("/api/files").json() == {"files": [], "enabled": False}
    assert off.post("/api/files", params={"name": "a.pdf"}, content=b"x").status_code == 404


def document(name="Code CIMA.pdf", id="wamid.9", media="MEDIA1"):
    return {"from": "221771234567", "id": id, "type": "document", "document": {"id": media, "filename": name, "mime_type": "application/pdf"}}


def test_a_document_sent_on_whatsapp_is_kept_and_acknowledged(tmp_path):
    bot, meta = make_bot(meta=Meta(recording=b"%PDF-1.4"))
    bot.files = UserFiles(tmp_path)
    bot.handle(payload(document()))
    assert (tmp_path / "221771234567" / "Code CIMA.pdf").read_bytes() == b"%PDF-1.4"
    assert [m["type"] for m in meta.sent] == ["text"] and "Code CIMA.pdf" in meta.sent[0]["text"]["body"]


def test_whatsapp_refuses_a_file_it_cannot_use_and_works_without_a_store(tmp_path):
    bot, meta = make_bot(meta=Meta(recording=b"MZ"))
    bot.files = UserFiles(tmp_path)
    bot.handle(payload(document("tool.exe")))
    assert not list((tmp_path / "221771234567").glob("*")) and "cannot be used" in meta.sent[0]["text"]["body"]
    bot2, meta2 = make_bot(meta=Meta(recording=b"%PDF"))          # no file store: the old "only voice and text" answer
    bot2.handle(payload(document(id="wamid.10")))
    assert "voice notes" in meta2.sent[0]["text"]["body"]
