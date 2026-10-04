import pytest

from waxal_agent.engines import build_engines


def test_engine_names(monkeypatch):
    monkeypatch.setenv("SOYNADE_API_KEY", "k")
    assert [type(e).__name__ for e in build_engines("fake")] == ["FakeListener", "FakeTranslator", "FakeSpeaker"]
    assert [type(e).__name__ for e in build_engines("soynade-asr")] == ["SoynadeListener", "FakeTranslator", "FakeSpeaker"]
    with pytest.raises(SystemExit, match="not wired yet"):
        build_engines("soynade")
    with pytest.raises(SystemExit, match="Unknown engines"):
        build_engines("whisper")


def test_nothing_in_the_package_loads_a_model():
    """Hosted APIs only: no model library is imported by the code."""
    from pathlib import Path
    import waxal_agent
    for path in Path(waxal_agent.__file__).parent.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for library in ("import torch", "from transformers", "import transformers", "huggingface_hub"):
            assert library not in text, (path, library)
