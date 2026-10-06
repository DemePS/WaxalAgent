import pytest
from coding_agent import state
from coding_agent.common import ToolError
from coding_agent.tools import TOOL_HANDLERS

from tests.test_pipeline import StubAgent
from waxal_agent import agent as module
from waxal_agent.links import LinkRefused, check_link
from waxal_agent.mt.fake import FakeTranslator
from waxal_agent.pipeline import Pipeline
from waxal_agent.stt.fake import FakeListener
from waxal_agent.tts.fake import FakeSpeaker
from waxal_agent.voice_ui import VoiceUI
from waxal_agent.whatsapp import with_links


@pytest.fixture(autouse=True)
def renassur(monkeypatch):
    monkeypatch.setenv("WAXAL_LINK_DOMAINS", "renassur.sn")


def test_an_https_link_to_an_allowed_site_or_its_subdomain_is_accepted():
    assert check_link("https://renassur.sn/", "Renassur") == {"url": "https://renassur.sn/", "label": "Renassur"}
    assert check_link("https://www.renassur.sn/contact?x=1")["label"] == "www.renassur.sn"      # no label: the site's name


@pytest.mark.parametrize("url", [
    "http://renassur.sn/", "ftp://renassur.sn/", "file:///etc/passwd", "javascript:alert(1)", "//renassur.sn/",
    "https://evil.com/", "https://renassur.sn.evil.com/", "https://evilrenassur.sn/", "https://renassur.sn@evil.com/",
    "https://evil.com@renassur.sn/", "https://renassur.sn:8443/", "https://renassur.sn/a b", "https://renassur.sn/\nx", "", "x" * 600,
])
def test_anything_else_is_refused(url):
    with pytest.raises(LinkRefused):
        check_link(url)


def test_without_allowed_domains_nothing_is_shared(monkeypatch):
    monkeypatch.delenv("WAXAL_LINK_DOMAINS")
    with pytest.raises(LinkRefused, match="No website is allowed"):
        check_link("https://renassur.sn/")


def test_the_label_is_short_plain_text():
    assert check_link("https://renassur.sn/", "A\nB" + "x" * 200)["label"].startswith("A B") and len(check_link("https://renassur.sn/", "x" * 200)["label"]) == 80


def test_the_tool_collects_links_once_and_tells_the_agent_when_it_is_refused():
    assert "share_link" in module.TOOLS and "share_link" in TOOL_HANDLERS and "web_search" in module.TOOLS
    state.ui = VoiceUI()
    assert "not" in TOOL_HANDLERS["share_link"](url="https://renassur.sn/a", label="Renassur").lower()
    TOOL_HANDLERS["share_link"](url="https://renassur.sn/a", label="again")
    assert state.ui.links == [{"url": "https://renassur.sn/a", "label": "Renassur"}]
    with pytest.raises(ToolError, match="not allowed"):
        TOOL_HANDLERS["share_link"](url="https://evil.com/")
    assert len(state.ui.links) == 1


def test_the_pipeline_returns_the_links_of_the_turn_and_not_the_ones_of_another_agent():
    class Sharing(StubAgent):
        def ask_full(self, user_id, question):
            return "Voir le site.", [], [{"url": "https://renassur.sn/", "label": "Renassur"}]
    result = Pipeline(FakeListener(default="naka"), FakeTranslator(), FakeSpeaker(), Sharing()).from_wolof("u", "naka")
    assert result.links == [{"url": "https://renassur.sn/", "label": "Renassur"}] and result.reply_wolof
    plain = Pipeline(FakeListener(default="naka"), FakeTranslator(), FakeSpeaker(), StubAgent()).from_wolof("u", "naka")
    assert plain.links == []


def test_the_links_are_in_the_json_and_under_the_text_on_whatsapp():
    from waxal_agent.server import as_json
    from waxal_agent.pipeline import TurnResult
    links = [{"url": "https://renassur.sn/", "label": "Renassur"}]
    assert as_json(TurnResult(links=links))["links"] == links
    assert with_links("Salaam.", links) == "Salaam.\n\nRenassur: https://renassur.sn/" and with_links("Salaam.", []) == "Salaam."


def test_the_page_shows_the_links_as_safe_anchors():
    from fastapi.testclient import TestClient
    from waxal_agent.server import create_app
    page = TestClient(create_app(Pipeline(FakeListener(), FakeTranslator(), FakeSpeaker(), StubAgent()))).get("/").text
    assert "links(e.links)" in page and "noopener noreferrer" in page and "textContent = k.label" in page    # text, never innerHTML


def test_the_prompt_lists_the_allowed_sites_only_when_there_are_some(tmp_path, monkeypatch):
    turns = module.AgentTurns(tmp_path / "users")
    assert "share_link" in turns.prompt_for_turn() and "renassur.sn" in turns.prompt_for_turn()
    monkeypatch.delenv("WAXAL_LINK_DOMAINS")
    assert "share_link" not in turns.prompt_for_turn()


def test_a_configured_name_is_the_label_whatever_the_agent_wrote(monkeypatch):
    monkeypatch.setenv("WAXAL_LINK_DOMAINS", "renassur.sn=Renassur, example.sn")
    from waxal_agent.links import allowed_domains
    assert allowed_domains() == ["renassur.sn", "example.sn"]
    assert check_link("https://www.renassur.sn/", "insurance company")["label"] == "Renassur"
    assert check_link("https://example.sn/", "The regulator")["label"] == "The regulator"      # no name configured: the agent's label
    assert check_link("https://example.sn/")["label"] == "example.sn"
