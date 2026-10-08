"""The log format and the noisy libraries. Part of the core: the agent's worker processes start from scratch and call setup_logging too, or
their lines are lost (they must not import the command line for it)."""

import logging


def quiet_loggers() -> None:
    """Libraries whose log lines only pollute the terminal: httpx logs one line per HTTP request (and httpcore, under it, a dozen at
    DEBUG), azure.identity its credential probing, pypdf a warning per font and page while it reads a PDF (a long PDF prints thousands of them)."""
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("pypdf").setLevel(logging.ERROR)


def setup_logging(level: str = "INFO") -> None:
    """The log format and level (WAXAL_LOG, through Settings.log_level)."""
    logging.basicConfig(level=level.upper(), format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    quiet_loggers()
