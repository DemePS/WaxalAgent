from types import SimpleNamespace

import pytest

from waxal_agent.mt.claude_api import ClaudeTranslator


class Messages:
    def __init__(self, answer="Nanga def?", reject_temperature=False):
        self.answer, self.reject_temperature, self.requests = answer, reject_temperature, []

    def create(self, **request):
        if self.reject_temperature and "temperature" in request:
            raise ValueError("temperature is not supported by this model")
        self.requests.append(request)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=f"  {self.answer} \n")])


def translator(messages, model="claude-test"):
    return ClaudeTranslator(client=SimpleNamespace(messages=messages), model=model)


def test_english_to_wolof_is_asked_for_in_standard_spelling_at_temperature_zero():
    messages = Messages()
    assert translator(messages).translate("How are you?", "en", "wo") == "Nanga def?"
    request = messages.requests[0]
    assert request["temperature"] == 0 and request["thinking"] == {"type": "between_tools"} and request["model"] == "claude-test" and request["messages"] == [{"role": "user", "content": "How are you?"}]
    assert "from English into Wolof" in request["system"] and "CAADA" in request["system"] and "translation only" in request["system"]


def test_wolof_to_english_allows_for_speech_recognition_mistakes():
    messages = Messages("How are you?")
    assert translator(messages).translate("Nanga def?", "wo", "en") == "How are you?"
    assert "from Wolof into English" in messages.requests[0]["system"] and "speech recognition" in messages.requests[0]["system"]


def test_same_language_and_empty_text_make_no_call():
    messages = Messages()
    t = translator(messages)
    assert t.translate("Nanga def?", "wo", "wo") == "Nanga def?" and t.translate("  ", "en", "wo") == "  " and messages.requests == []


def test_a_model_without_temperature_is_asked_again_without_it_and_other_errors_surface():
    messages = Messages(reject_temperature=True)
    assert translator(messages).translate("Hello", "en", "wo") == "Nanga def?" and "temperature" not in messages.requests[0]
    assert messages.requests[0]["thinking"] == {"type": "between_tools"}            # only the refused setting was dropped

    class Broken:
        def create(self, **request):
            raise RuntimeError("overloaded")
    with pytest.raises(RuntimeError, match="overloaded"):
        ClaudeTranslator(client=SimpleNamespace(messages=Broken())).translate("Hello", "en", "wo")


def test_an_empty_answer_because_the_budget_ran_out_is_asked_again_with_more_room():
    calls = []

    class Budget:
        def create(self, **request):
            calls.append(request["max_tokens"])
            if len(calls) == 1:
                return SimpleNamespace(content=[SimpleNamespace(type="thinking", text="")], stop_reason="max_tokens")
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="How are you?")], stop_reason="end_turn")
    assert ClaudeTranslator(client=SimpleNamespace(messages=Budget()), model="m").translate("Nanga def?", "wo", "en") == "How are you?"
    assert calls[1] == calls[0] * 4


def test_an_empty_answer_says_why():
    class Refusing:
        def create(self, **request):
            return SimpleNamespace(content=[], stop_reason="refusal")
    with pytest.raises(ValueError, match=r"stop reason: refusal.*content: empty.*model: m"):
        ClaudeTranslator(client=SimpleNamespace(messages=Refusing()), model="m").translate("Nanga def?", "wo", "en")


def test_a_model_that_refuses_to_have_thinking_disabled_is_asked_again_with_it_left_alone():
    class NoSwitch:
        requests = []

        def create(self, **request):
            if "thinking" in request:
                raise ValueError("thinking cannot be disabled for this model")
            self.requests.append(request)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="Nanga def?")], stop_reason="end_turn")
    messages = NoSwitch()
    assert translator(messages).translate("Hello", "en", "wo") == "Nanga def?" and messages.requests[0]["temperature"] == 0


def test_the_first_accepted_combination_is_remembered_so_later_calls_do_not_fail_again():
    calls = []

    class Sonnet55:                                   # no temperature, thinking only through between_tools
        def create(self, **request):
            calls.append(sorted(k for k in request if k in ("temperature", "thinking")))
            if "temperature" in request:
                raise ValueError("temperature: non-default values are not supported")
            if request.get("thinking") != {"type": "between_tools"}:
                raise ValueError("thinking: use between_tools")
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="Nanga def?")], stop_reason="end_turn")
    t = ClaudeTranslator(client=SimpleNamespace(messages=Sonnet55()), model="m")
    assert t.translate("Hello", "en", "wo") == "Nanga def?" and calls == [["temperature", "thinking"], ["thinking"]]
    assert t.translate("Thanks", "en", "wo") == "Nanga def?" and calls[2:] == [["thinking"]]      # one call, no failed attempts


def test_the_translation_model_is_opus_not_the_agents_unless_it_is_set_or_foundry_is_used(monkeypatch):
    from waxal_agent.mt import claude_api
    monkeypatch.delenv("ANTHROPIC_FOUNDRY_ENDPOINT", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")                         # the agent's model
    assert claude_api.default_model() == "claude-opus-5"
    messages = Messages()
    ClaudeTranslator(client=SimpleNamespace(messages=messages)).translate("Hello", "en", "wo")
    assert messages.requests[0]["model"] == "claude-opus-5"
    monkeypatch.setenv("WAXAL_MT_MODEL", "claude-opus-5-5")
    messages = Messages()
    ClaudeTranslator(client=SimpleNamespace(messages=messages)).translate("Hello", "en", "wo")
    assert messages.requests[0]["model"] == "claude-opus-5-5"
    monkeypatch.delenv("WAXAL_MT_MODEL")
    monkeypatch.setenv("ANTHROPIC_FOUNDRY_ENDPOINT", "https://x.example/anthropic")      # Foundry: a model name is a deployment name
    monkeypatch.setenv("ANTHROPIC_FOUNDRY_DEPLOYMENT", "my-deployment")
    assert claude_api.default_model() == "my-deployment"


def test_a_translation_style_prompt_is_added_to_the_wolof_translation_only(tmp_path, monkeypatch):
    style = tmp_path / "translation_style_prompt.md"
    style.write_text("Write *jàmm* not *jamm*. Glossary: {balance} = *sold*.\n", encoding="utf-8")
    monkeypatch.setenv("WAXAL_TRANSLATION_STYLE", str(style))
    messages = Messages()
    translator(messages).translate("How are you?", "en", "wo")
    translator(messages).translate("Nanga def?", "wo", "en")
    wolof, english = messages.requests[0]["system"], messages.requests[1]["system"]
    assert "CAADA" in wolof and "Write *jàmm* not *jamm*" in wolof and "{balance} = *sold*" in wolof
    assert "jàmm" not in english
    style.write_text("Say *jërejëf*.", encoding="utf-8")  # read at every translation: no restart
    translator(messages).translate("Thanks", "en", "wo")
    assert "jërejëf" in messages.requests[2]["system"] and "jàmm" not in messages.requests[2]["system"]


def test_a_missing_or_empty_style_file_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("WAXAL_TRANSLATION_STYLE", str(tmp_path / "none.md"))
    messages = Messages()
    translator(messages).translate("How are you?", "en", "wo")
    (tmp_path / "empty.md").write_text("  \n")
    monkeypatch.setenv("WAXAL_TRANSLATION_STYLE", str(tmp_path / "empty.md"))
    translator(messages).translate("How are you?", "en", "wo")
    assert all("Style guide" not in r["system"] for r in messages.requests)
