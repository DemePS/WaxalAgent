"""Settings and Language are plain values: built from an environment given to them, never read when a module is imported."""

import pytest

pytest.importorskip("fastapi")  # the web layer is an extra: the core's tests run without it
from fastapi.testclient import TestClient

from tests.test_pipeline import StubAgent
from waxal_agent.files import Library
from waxal_agent.language import Language
from waxal_agent.mt.fake import FakeTranslator
from waxal_agent.pipeline import Pipeline
from waxal_agent.settings import MB, Settings
from waxal_agent.stt.fake import FakeListener
from waxal_agent.tts.fake import FakeSpeaker
from waxal_server.app import create_app


def test_the_defaults_are_what_the_program_does_with_nothing_set():
    s = Settings.from_env({})
    assert s == Settings()
    assert (s.language, s.stt, s.mt, s.tts) == (Language(), "elevenlabs", "claude", "elevenlabs")
    assert (s.direct, s.show_wolof, s.workers, s.token, s.developer_mode, s.cleanup) == (True, False, 4, None, False, True)
    assert (s.documents, s.instructions, s.skills, s.data) == ("data/documents", "data/instructions", "data/skills", "data/users")
    assert s.max_upload_bytes == 20 * MB and s.s3_bucket is None and s.log_level == "INFO"


def test_every_setting_comes_from_its_variable_and_an_empty_variable_is_an_unset_one():
    s = Settings.from_env({
        "WAXAL_STT": "Soynade", "WAXAL_MT": "soynade", "WAXAL_TTS": "soynade", "WAXAL_DIRECT": "off", "WAXAL_SHOW_WOLOF": "1",
        "WAXAL_WORKERS": "2", "WAXAL_DOCUMENTS": "docs", "WAXAL_INSTRUCTIONS_DIR": "ins", "WAXAL_SKILLS_DIR": "sk",
        "WAXAL_MAX_UPLOAD_MB": "0.5", "WAXAL_TOKEN": "secret", "DEVELOPER_MODE": "true", "WAXAL_CLEANUP": "off",
        "WAXAL_LOG": "debug", "WAXAL_S3_BUCKET": "b", "WAXAL_S3_USERS_PREFIX": "u/", "WAXAL_REPLY_LANGUAGE": "wo",
        "WAXAL_TRANSLATION": "",
    })
    assert (s.stt, s.mt, s.tts) == ("soynade",) * 3
    assert (s.direct, s.show_wolof, s.workers, s.cleanup, s.developer_mode) == (False, True, 2, False, True)
    assert (s.documents, s.instructions, s.skills, s.max_upload_bytes) == ("docs", "ins", "sk", MB // 2)
    assert (s.token, s.log_level, s.s3_bucket, s.s3_users_prefix, s.s3_shared_prefix) == ("secret", "DEBUG", "b", "u/", "documents/")
    assert s.language == Language(translation_on=True, reply_language="wo") and s.language.translating is False
    assert Settings.from_env({"WAXAL_TOKEN": "", "WAXAL_S3_BUCKET": "  "}).token is None


def test_two_settings_live_in_the_same_process_and_the_environment_is_only_read_when_asked(monkeypatch):
    monkeypatch.setenv("WAXAL_REPLY_LANGUAGE", "fr")
    first = Settings.from_env()
    monkeypatch.setenv("WAXAL_REPLY_LANGUAGE", "en")
    assert first.language.reply_language == "fr" and Settings.from_env().language.reply_language == "en"
    assert first.with_(token="t").token == "t" and first.token is None          # a copy: the original is not changed
    with pytest.raises(Exception):
        first.token = "x"                                                      # frozen


def test_the_language_decides_what_is_translated_and_what_the_engines_listen_and_speak():
    assert (Language().translating, Language().name, Language().source, Language().stt_code, Language().tts_code) == (True, "English", "en", "wol", "fr")
    fr = Language(translation_on=False, reply_language="fr")
    assert (fr.translating, fr.name, fr.stt_code, fr.tts_code) == (False, "French", "fra", "fr")
    assert Language(reply_language="wo").translating is False
    assert Language(reply_language="pt").name == "pt"                           # an unknown language is named by its code


def test_the_health_endpoint_tells_the_page_how_to_lay_itself_out(tmp_path):
    def health(language):
        pipe = Pipeline(FakeListener(default="x"), FakeTranslator(), FakeSpeaker(), StubAgent(), language=language)
        return TestClient(create_app(pipeline=pipe, files=Library(tmp_path))).get("/api/health").json()
    assert health(Language()) == {"ok": True, "translating": True, "language": "en"}
    assert health(Language(translation_on=False, reply_language="fr")) == {"ok": True, "translating": False, "language": "fr"}


def test_the_upload_limit_is_the_librarys_own(tmp_path):
    library = Library(tmp_path, max_bytes=10)
    pipe = Pipeline(FakeListener(default="x"), FakeTranslator(), FakeSpeaker(), StubAgent())
    client = TestClient(create_app(pipe, files=library))
    assert client.post("/api/files?name=a.txt", content=b"x" * 11).status_code in (400, 413)
    assert client.post("/api/files?name=a.txt", content=b"x" * 10).status_code == 200
