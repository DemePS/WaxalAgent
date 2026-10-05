"""Housekeeping: CodeAgent keeps each person's conversation and notes on disk and leaves the clean-up to the application that uses
it (cleanup.run()). WaxalAgent runs it when the server starts and then once a day, as it runs for weeks:

- saved conversations are deleted after AGENT_CONVERSATION_DAYS days without use (default 30),
- the whole memory of a person not used for AGENT_MEMORY_DAYS days (default 90),
- backups (not used here) after AGENT_BACKUP_DAYS days.

WAXAL_CLEANUP=off switches it off. The person's own files (data/users/...) are never touched.
"""

import logging
import os
import threading

log = logging.getLogger("waxal.cleanup")

INTERVAL_SECONDS = 24 * 3600


def run_once() -> str:
    from coding_agent import cleanup
    summary = cleanup.run()  # never raises
    log.info(summary)
    return summary


def start(interval: float = INTERVAL_SECONDS) -> threading.Thread | None:
    """Clean up now, then every `interval` seconds, in a background thread. None when switched off."""
    if (os.environ.get("WAXAL_CLEANUP") or "on").lower() in ("off", "0", "false", "no"):
        log.info("Clean-up of old conversations and notes is switched off (WAXAL_CLEANUP=off).")
        return None
    stop = threading.Event()

    def loop() -> None:
        while True:
            run_once()
            if stop.wait(interval):
                return
    thread = threading.Thread(target=loop, name="cleanup", daemon=True)
    thread.stop = stop.set  # type: ignore[attr-defined]
    thread.start()
    return thread
