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
import socket
from urllib.parse import urlsplit

from coding_agent.common import ToolError
from coding_agent.tools import TOOL_HANDLERS
from coding_agent.tools import web as _web

from .links import allowed_domains

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
            return False
        parts = urlsplit(request_url)
        if parts.scheme in ("http", "https", "ws", "wss"):
            host = parts.hostname or ""
            if host not in _private_hosts:
                _private_hosts[host] = _private(host)
            return not _private_hosts[host]
        return True
    request_allowed.waxal = True
    return request_allowed


def _web_open(original):
    def web_open(url: str) -> str:
        target = (url or "").strip()
        if "://" not in target:
            target = "https://" + target
        if not on_allowed_site(target):
            raise ToolError("Only an https address on one of these websites can be opened: " + (", ".join(allowed_domains()) or "(none allowed)")
                            + ". Do not try another address.")
        _web._B.approved.add(urlsplit(target).hostname.lower())  # approved in advance: nobody can be asked in this channel
        return original(target)
    web_open.waxal = True
    return web_open


def install() -> None:
    """Put the rules in place (once)."""
    if not getattr(_web.request_allowed, "waxal", False):
        _web.request_allowed = _strict(_web.request_allowed)
    if not getattr(TOOL_HANDLERS["web_open"], "waxal", False):
        TOOL_HANDLERS["web_open"] = _web_open(TOOL_HANDLERS["web_open"])


def reset() -> None:
    """Close the browser (end of a turn): its cookies, its history and its open page go with it."""
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
