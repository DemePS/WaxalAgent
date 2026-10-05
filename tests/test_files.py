import pytest
from fastapi.testclient import TestClient

from tests.test_pipeline import StubAgent
from tests.test_server import client as plain_client
from tests.test_whatsapp import CONFIG, Meta, make_bot, payload
from waxal_agent import files as files_module
from waxal_agent.files import FileRefused, Library, safe_name
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


def test_the_library_saves_lists_never_overwrites_and_deletes(tmp_path):
    library = Library(tmp_path / "documents")                                      # created when missing
    assert library.save("code.pdf", b"one") == "code.pdf"
    assert library.save("code.pdf", b"two") == "code (2).pdf"                      # never overwritten
    assert [f["name"] for f in library.list()] == ["code (2).pdf", "code.pdf"]
    library.delete("code.pdf")
    assert [f["name"] for f in library.list()] == ["code (2).pdf"]
    with pytest.raises(FileRefused, match="No such file"):
        library.delete("code.pdf")


def test_empty_big_and_too_many_files_are_refused(tmp_path, monkeypatch):
    library = Library(tmp_path)
    with pytest.raises(FileRefused, match="empty"):
        library.save("a.txt", b"")
    monkeypatch.setattr(files_module, "MAX_BYTES", 10)
    with pytest.raises(FileRefused, match="too big"):
        library.save("a.txt", b"x" * 11)
    monkeypatch.setattr(files_module, "MAX_FILES", 1)
    library.save("a.txt", b"x")
    with pytest.raises(FileRefused, match="Too many"):
        library.save("b.txt", b"x")


def app_client(tmp_path, token=None):
    pipeline = Pipeline(FakeListener(default="naka"), FakeTranslator(), FakeSpeaker(), StubAgent())
    return TestClient(create_app(pipeline, token, files=Library(tmp_path)))


def test_the_page_can_upload_list_and_delete_in_the_shared_library(tmp_path):
    c = app_client(tmp_path)
    assert c.get("/api/files").json() == {"files": [], "enabled": True}
    r = c.post("/api/files", params={"name": "invoice.pdf"}, content=b"%PDF-1.4")
    assert r.status_code == 200 and r.json()["name"] == "invoice.pdf" and r.json()["files"] == [{"name": "invoice.pdf", "size": 8}]
    assert (tmp_path / "invoice.pdf").read_bytes() == b"%PDF-1.4"                  # one library, whoever asks
    assert TestClient(c.app).get("/api/files", headers={"x-user": "someone else"}).json()["files"] == [{"name": "invoice.pdf", "size": 8}]
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


def document(name="Code CIMA.pdf", id="wamid.9", media="MEDIA1", sender="221771234567"):
    return {"from": sender, "id": id, "type": "document", "document": {"id": media, "filename": name, "mime_type": "application/pdf"}}


def admin_bot(tmp_path, recording=b"%PDF-1.4"):
    bot, meta = make_bot(meta=Meta(recording=recording))
    bot.config.admins = {"221771234567"}
    bot.files = Library(tmp_path)
    return bot, meta


def test_a_document_sent_by_an_administrator_is_added_to_the_library(tmp_path):
    bot, meta = admin_bot(tmp_path)
    bot.handle(payload(document()))
    assert (tmp_path / "Code CIMA.pdf").read_bytes() == b"%PDF-1.4"
    assert [m["type"] for m in meta.sent] == ["text"] and "Code CIMA.pdf" in meta.sent[0]["text"]["body"]


def test_a_document_from_anyone_else_is_refused_and_a_bad_kind_is_explained(tmp_path):
    bot, meta = admin_bot(tmp_path)
    bot.config.allowed.add("221779999999")
    bot.handle(payload(document(sender="221779999999", id="wamid.20")))
    assert not list(tmp_path.glob("*")) and "administrators" in meta.sent[0]["text"]["body"]
    bot.handle(payload(document("tool.exe", id="wamid.21")))                        # an administrator, but not a usable kind
    assert not list(tmp_path.glob("*")) and "cannot be used" in meta.sent[1]["text"]["body"]
    bot2, meta2 = make_bot(meta=Meta(recording=b"%PDF"))                            # no library: the plain explanation
    bot2.handle(payload(document(id="wamid.22")))
    assert "voice notes" in meta2.sent[0]["text"]["body"]


def test_administrators_come_from_the_environment():
    from waxal_agent.whatsapp import WhatsAppConfig
    env = {"WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "p", "WHATSAPP_VERIFY_TOKEN": "v", "WHATSAPP_APP_SECRET": "s",
           "WAXAL_ALLOWED": "+221 77 123 45 67, 221 78 000 00 00", "WAXAL_ADMINS": "+221 77 123 45 67"}
    config = WhatsAppConfig.from_env(env)
    assert config.admins == {"221771234567"} and config.allowed == {"221771234567", "221780000000"}
