import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("timing_table", Path(__file__).parent.parent / "scripts" / "timing_table.py")
timing_table = importlib.util.module_from_spec(spec)
spec.loader.exec_module(timing_table)

LOG = """\
10:00:00 INFO [1] Wolof: some private words
10:00:01 INFO [3] asking the agent: a private question
10:00:02 INFO    the agent is thinking...
10:00:09 INFO    agent timing: first output after 2.4 s, 3 tool call(s), 21.0 s in all
10:00:09 INFO tokens: 12,000 in (8,000 cached), 1,234 out, 4 call(s)
10:00:09 INFO [3] agent answered (21.3 s): a private answer
10:00:12 INFO [6] timing: agent 21.3 s, translation 1.5 s, voice 3.2 s | first text at 22.8 s, first voice at 24.1 s | 27.0 s in all
"""


def test_the_numbers_of_a_turn_are_read_from_the_log():
    (turn,) = timing_table.parse(LOG.splitlines())
    assert turn == {"first_output_s": "2.4", "tools": "3", "calls": "4", "out_tokens": "1234", "agent_s": "21.3", "translation_s": "1.5",
                    "voice_s": "3.2", "first_text_s": "22.8", "first_voice_s": "24.1", "total_s": "27.0"}


def test_the_table_has_numbers_only():
    text = timing_table.table(timing_table.parse(LOG.splitlines()))
    assert "21.3" in text and "27.0" in text
    assert "private" not in text
