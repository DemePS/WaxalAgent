import logging

from waxal_agent.logs import setup_logging


def test_the_conversation_recap_is_hidden_at_info_and_shown_at_debug(capsys):
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    try:
        for level, shown in (("INFO", False), ("DEBUG", True)):
            root.handlers.clear()
            setup_logging(level)
            log = logging.getLogger("coding_agent")
            log.info("Resumed conversation: 6 earlier instruction(s)")
            log.info("Last instruction: a question")
            log.info("[context] 92k / 200k tokens")
            err = capsys.readouterr().err
            assert ("Resumed conversation" in err and "Last instruction" in err) == shown
            assert "[context]" in err
    finally:
        root.handlers[:], root.level = saved[0], saved[1]
