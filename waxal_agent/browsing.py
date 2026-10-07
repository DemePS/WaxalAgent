"""Browsing for the agent: CodeAgent's headless browser (web_open, web_click, web_page, web_back, web_close), limited to the websites of
WAXAL_LINK_DOMAINS, so that it can find the right page of the partner's site and share its address (share_link).

CodeAgent's browser asks a person before it opens a new site, and the voice channel answers every question "no". Here the allowed sites are the
ones that were approved in advance, and nothing else can be opened. Three rules on top of CodeAgent's own (it already refuses link-local and
cloud-metadata addresses, passwords, payment fields, downloads, and sends no form without asking):

- web_open takes only an https address on an allowed website;
- the pages' own requests and the clicks never reach a local or private network address (CodeAgent lets them through, for development);
- the browser is closed after every turn, so that nothing of one person (cookies, history, the open page) reaches the next one.
"""

import importlib.util
import ipaddress
import logging
import os
import socket
from urllib.parse import urlsplit

from coding_agent.common import ToolError
from coding_agent.tools import TOOL_HANDLERS
from coding_agent.tools import web as _web

from .links import allowed_domains

log = logging.getLogger(__name__)

BROWSER_TOOLS = ["web_open", "web_click", "web_page", "web_back", "web_close"]  # not web_type, web_sign_in, web_look: nobody types for the person


def on_allowed_site(url: str) -> bool:
    """An https address, without a login part or a port, on an allowed website or one of its subdomains."""
    parts = urlsplit(url or "")
    if parts.scheme != "https" or not parts.hostname or "@" in parts.netloc or parts.port not in (None, 443):
        return False
    host = parts.hostname.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in allowed_domains())


def _private(host: str) -> bool:
    """A loopback, private, link-local... address (the name is resolved). An unknown name counts as private: nothing is sent to it."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            return True
    return False


_private_hosts: dict[str, bool] = {}


def _strict(original):
    def request_allowed(request_url: str, host_ok: dict) -> bool:
        if not original(request_url, host_ok):
            log.warning("   browser: a page request was refused by CodeAgent: %s", request_url[:150])
            return False
        parts = urlsplit(request_url)
        if parts.scheme in ("http", "https", "ws", "wss"):
            host = parts.hostname or ""
            if host not in _private_hosts:
                _private_hosts[host] = _private(host)
            if _private_hosts[host]:
                log.warning("   browser: a page request to %s was refused (local, private or unknown address): %s", host, request_url[:150])
            return not _private_hosts[host]
        return True
    request_allowed.waxal = True
    return request_allowed


MAX_OPENS = 3  # web_open calls in one turn (WAXAL_MAX_WEB_OPEN): then the agent answers with what it has read
_opens = 0


def max_opens() -> int:
    try:
        return max(1, int(os.environ.get("WAXAL_MAX_WEB_OPEN") or MAX_OPENS))
    except ValueError:
        return MAX_OPENS


SETTLE_MAX = 10.0  # seconds a page may keep filling itself after it was opened (a search page shows its results after a script call)
SETTLE_QUIET = 3.0  # seconds without any change in its text: it is finished


def _wait_until_still(browser) -> bool:
    """Wait until the text of the open page stops changing (at most SETTLE_MAX s); True when it changed while waiting."""
    page = browser.ensure_page()
    size = lambda: page.evaluate("document.body ? document.body.innerText.length : 0")
    first = last = size()
    still = waited = 0.0
    while waited < SETTLE_MAX and still < SETTLE_QUIET:
        page.wait_for_timeout(500)
        waited += 0.5
        now = size()
        still = still + 0.5 if now == last else 0.0
        last = now
    return last != first


def _web_open(original):
    def web_open(url: str) -> str:
        global _opens
        target = (url or "").strip()
        if "://" not in target:
            target = "https://" + target
        if not on_allowed_site(target):
            raise ToolError("Only an https address on one of these websites can be opened: " + (", ".join(allowed_domains()) or "(none allowed)")
                            + ". Do not try another address.")
        if _opens >= max_opens():
            raise ToolError(f"web_open was already used {max_opens()} times for this question: no more pages. Answer now from what you have read "
                            "(web_click and web_page still work on the page that is open).")
        _opens += 1
        _web._B.approved.add(urlsplit(target).hostname.lower())  # approved in advance: nobody can be asked in this channel
        page = original(target)
        try:
            if _web._B.call(_wait_until_still):  # the page filled itself after the load: read it again
                log.info("   browser: %s filled itself after the load, read again", target)
                return _web._render(_web._B.call(lambda b: b.snapshot()))
        except Exception:  # the wait is a help, never a failure
            pass
        return page
    web_open.waxal = True
    return web_open


def install() -> None:
    """Put the rules in place (once)."""
    if not getattr(_web.request_allowed, "waxal", False):
        _web.request_allowed = _strict(_web.request_allowed)
    if not getattr(TOOL_HANDLERS["web_open"], "waxal", False):
        TOOL_HANDLERS["web_open"] = _web_open(TOOL_HANDLERS["web_open"])


def reset() -> None:
    """Close the browser (end of a turn): its cookies, its history and its open page go with it. The web_open count starts again."""
    global _opens
    _opens = 0
    try:
        _web._B.close()
    except Exception:  # nothing was open, or Playwright is not installed
        pass


def available() -> bool:
    return importlib.util.find_spec("playwright") is not None


def report() -> str:
    """The start-up line: which sites can be browsed, and whether the browser is there."""
    sites = ", ".join(allowed_domains())
    if not sites:
        return "Browsing: off (WAXAL_LINK_DOMAINS is not set: no website may be opened)."
    if not available():
        return f"Browsing: sites {sites}, but Playwright is not installed (uv sync --extra browser, then: playwright install chromium)."
    return f"Browsing: sites {sites} (headless browser, closed after every turn)."
