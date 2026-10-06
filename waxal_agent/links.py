"""Links the agent may share with the person (the share_link tool): https only, and only on the sites of WAXAL_LINK_DOMAINS.

    WAXAL_LINK_DOMAINS=renassur.sn,example.sn      a site and its subdomains (www.renassur.sn, ...)
    WAXAL_LINK_DOMAINS=renassur.sn=Renassur        with the name shown for it: then that name is the label, whatever the agent wrote

Not set: no link is allowed (nothing is shared by accident). A refusal says why, to the agent, so it can answer without the link."""

import os
import re
from urllib.parse import urlsplit

MAX_URL = 500
MAX_LABEL = 80


class LinkRefused(ValueError):
    """The link cannot be shared; the message is for the agent."""


def _entries() -> list[tuple[str, str]]:
    """[(domain, name shown for it or "")] from WAXAL_LINK_DOMAINS."""
    entries = []
    for item in (os.environ.get("WAXAL_LINK_DOMAINS") or "").split(","):
        domain, _, name = item.partition("=")
        if domain.strip():
            entries.append((domain.strip().lower().lstrip("."), name.strip()))
    return entries


def allowed_domains() -> list[str]:
    return [domain for domain, _ in _entries()]


def check_link(url: str, label: str = "") -> dict:
    """{"url", "label"} for a link that may be shared, else LinkRefused."""
    domains = allowed_domains()
    names = dict(_entries())
    if not domains:
        raise LinkRefused("No website is allowed for links: do not share a link, answer without it.")
    url = (url or "").strip()
    if len(url) > MAX_URL or re.search(r"[\s\x00-\x1f]", url):
        raise LinkRefused("That is not a valid link.")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or "@" in parts.netloc or parts.port not in (None, 443):
        raise LinkRefused("Only plain https links to an allowed website can be shared.")
    host = parts.hostname.lower().rstrip(".")
    domain = next((d for d in domains if host == d or host.endswith("." + d)), None)
    if domain is None:
        raise LinkRefused(f"Links to {host} are not allowed; the allowed websites are: {', '.join(domains)}.")
    label = names[domain] or re.sub(r"[\x00-\x1f]+", " ", label or "").strip()[:MAX_LABEL] or host  # a configured name wins over the agent's label
    return {"url": url, "label": label}
