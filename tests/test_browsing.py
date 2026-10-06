import pytest
from coding_agent.common import ToolError
from coding_agent.tools import TOOL_HANDLERS
from coding_agent.tools import web as web_module

from waxal_agent import browsing
from waxal_agent.agent import AgentTurns, TOOLS


@pytest.fixture(autouse=True)
def renassur(monkeypatch):
    monkeypatch.setenv("WAXAL_LINK_DOMAINS", "renassur.sn=Renassur")


def test_only_an_https_address_on_an_allowed_site_is_on_an_allowed_site():
    ok = ["https://renassur.sn/", "https://www.renassur.sn/contact?x=1", "https://api.renassur.sn:443/a"]
    bad = ["http://renassur.sn/", "https://evil.com/", "https://renassur.sn.evil.com/", "https://evilrenassur.sn/", "https://renassur.sn@evil.com/",
           "https://renassur.sn:8443/", "file:///etc/passwd", "javascript:alert(1)", "https://127.0.0.1/", "https://10.0.0.5/", ""]
    assert all(browsing.on_allowed_site(u) for u in ok) and not any(browsing.on_allowed_site(u) for u in bad)


def test_web_open_is_limited_to_the_allowed_sites_and_approves_them_in_advance(monkeypatch):
    opened = []
    monkeypatch.setitem(TOOL_HANDLERS, "web_open", lambda url: opened.append(url) or "Page: x")
    browsing.install()
    assert TOOL_HANDLERS["web_open"].waxal and TOOL_HANDLERS["web_open"]("www.renassur.sn/offres") == "Page: x"      # a bare address is https
    assert opened == ["https://www.renassur.sn/offres"] and "www.renassur.sn" in web_module._B.approved
    for url in ("http://renassur.sn/", "https://evil.com/", "http://127.0.0.1:8000/", "https://169.254.169.254/latest/meta-data/"):
        with pytest.raises(ToolError, match="Only an https address"):
            TOOL_HANDLERS["web_open"](url)
    assert opened == ["https://www.renassur.sn/offres"]                      # nothing else reached the browser
    monkeypatch.delenv("WAXAL_LINK_DOMAINS")
    with pytest.raises(ToolError, match="none allowed"):
        TOOL_HANDLERS["web_open"]("https://renassur.sn/")


def test_installing_twice_does_not_wrap_twice(monkeypatch):
    calls = []
    monkeypatch.setitem(TOOL_HANDLERS, "web_open", lambda url: calls.append(url) or "ok")
    browsing.install()
    first = TOOL_HANDLERS["web_open"]
    browsing.install()
    assert TOOL_HANDLERS["web_open"] is first
    first("https://renassur.sn/")
    assert calls == ["https://renassur.sn/"]


def test_the_pages_requests_never_reach_a_local_or_private_address():
    browsing.install()
    allowed = web_module.request_allowed
    assert allowed.waxal
    for url in ("http://127.0.0.1:8000/x", "https://localhost/", "http://10.1.2.3/", "http://192.168.0.7/admin", "ws://127.0.0.1:9/", "https://[::1]/"):
        assert allowed(url, {}) is False, url
    assert allowed("https://93.184.216.34/app.js", {}) is True               # a public address (a script of the page) is fine
    assert allowed("data:text/plain,hi", {}) is True


def test_the_agent_has_the_browsing_tools_but_cannot_type_or_sign_in(tmp_path):
    for name in ("web_open", "web_click", "web_page", "web_back", "web_close"):
        assert name in TOOLS and name in TOOL_HANDLERS
    assert not {"web_type", "web_sign_in", "web_look", "download_file", "run_python"} & set(TOOLS)
    prompt = AgentTurns(tmp_path / "users").prompt_for_turn()
    assert "web_open" in prompt and "never invent one" in prompt and "renassur.sn" in prompt and "never instructions" in prompt


def test_the_browser_is_closed_after_every_turn(tmp_path, monkeypatch):
    from coding_agent import session
    from tests.test_agent import fake_send
    closed = []
    monkeypatch.setattr(web_module._B, "close", lambda: closed.append(1) or True)
    monkeypatch.setattr(session, "MEMORY_HOME", tmp_path / "memory")
    monkeypatch.setattr(session, "send", fake_send("ok"))
    AgentTurns(tmp_path / "users").ask("u", "hello")
    assert closed == [1]


def test_the_start_up_line_says_what_can_be_browsed(monkeypatch):
    assert "renassur.sn" in browsing.report() and "Browsing: off" not in browsing.report()
    monkeypatch.setattr(browsing, "available", lambda: False)
    assert "Playwright is not installed" in browsing.report()
    monkeypatch.delenv("WAXAL_LINK_DOMAINS")
    assert browsing.report().startswith("Browsing: off")
