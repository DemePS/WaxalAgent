"""Open a page the way the agent does (the allowed-sites rules, the wait for pages that fill themselves) and print what it reads.

    uv run --extra browser python scripts/check_browse.py "https://renassur.sn/search?q=assurance"

The site of the address is allowed for the run. Requests that the browser rules refuse are logged as warnings ("browser: ..."), which tells
why a page that works in CodeAgent alone shows nothing here. Needs Playwright (uv sync --extra browser, then: playwright install chromium).
"""

import logging
import sys
from urllib.parse import urlsplit

from waxal_agent.cli import load_env

load_env()

from coding_agent import state  # noqa: E402
from coding_agent.tools import TOOL_HANDLERS  # noqa: E402

from waxal_agent import agent, browsing  # noqa: E402,F401  (importing agent installs the browser rules)


class _UI:
    def status(self, *args):
        pass


if len(sys.argv) < 2:
    sys.exit(__doc__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
url = sys.argv[1]
import os  # noqa: E402
os.environ.setdefault("WAXAL_LINK_DOMAINS", urlsplit(url).hostname or "")
state.ui = _UI()
try:
    print(TOOL_HANDLERS["web_open"](url)[:3000])
finally:
    browsing.reset()
