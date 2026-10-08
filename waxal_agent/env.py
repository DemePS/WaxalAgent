"""Loading a .env file into the environment, before Settings.from_env() reads it."""

import os
from pathlib import Path


def load_env() -> None:
    """The settings of a .env file: the first .env found from the folder you run in upwards, then ~/.coding-agent/.env, as CodeAgent does.
    A variable already set in the environment wins.

    WAXAL_LINK_DOMAINS is only a safety whitelist (the domains browsing and share_link may ever reach, see links.py); it does not change
    which tools the agent has. Whether hosted web search (AGENT_WEB_SEARCH) is on, and whether the agent should check the allowed websites
    before the library, are choices for whoever runs the deployment: set AGENT_WEB_SEARCH directly, and say the rest in plain words in the
    instructions folder (WAXAL_INSTRUCTIONS_DIR) -- its files are appended to the agent's system prompt and win over the rest of it."""
    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv(usecwd=True))
    load_dotenv(Path(os.environ.get("HOME") or Path.home()).expanduser() / ".coding-agent" / ".env")
