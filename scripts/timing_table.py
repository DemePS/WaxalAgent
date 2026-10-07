"""Where the time of each turn went, from the server's log (the lines `[3] agent answered`, `agent timing`, `tokens:` and `[6] timing`).

    uv run python scripts/timing_table.py server.log          # or:  uv run waxal-agent serve 2>&1 | tee server.log   then ask a question
    uv run python scripts/timing_table.py < server.log

One row per turn. Only numbers are printed: never a question, an answer, a user or a key. A turn is counted from the `[3] asking the agent` line.
One or a few turns are directional, not a benchmark.
"""

import re
import sys

NUMBER = r"(\d+(?:\.\d+)?)"
PATTERNS = {
    "agent_s": re.compile(r"\[3\] agent answered \(" + NUMBER + r" s\)"),
    "first_output_s": re.compile(r"agent timing: first output after " + NUMBER + r" s"),
    "tools": re.compile(r"agent timing: .*?, (\d+) tool call\(s\)"),
    "calls": re.compile(r"tokens: .*?, (\d+) call\(s\)"),
    "out_tokens": re.compile(r"tokens: .*?\), ([\d,]+) out"),
    "translation_s": re.compile(r"\[6\] timing: agent \S+ s?,? ?translation " + NUMBER + r" s"),
    "voice_s": re.compile(r"\[6\] timing: .*? voice " + NUMBER + r" s"),
    "first_text_s": re.compile(r"first text at " + NUMBER + r" s"),
    "first_voice_s": re.compile(r"first voice at " + NUMBER + r" s"),
    "total_s": re.compile(r"\[6\] timing: .*?\| " + NUMBER + r" s in all"),
}
COLUMNS = [("agent_s", "agent s"), ("first_output_s", "1st output s"), ("calls", "model calls"), ("tools", "tool calls"),
           ("out_tokens", "out tokens"), ("translation_s", "transl. s"), ("voice_s", "voice s"), ("first_text_s", "1st text s"),
           ("first_voice_s", "1st voice s"), ("total_s", "after agent asked s")]


def parse(lines) -> list[dict]:
    """One dict per turn: the numbers found between a `[3] asking the agent` line and the next one."""
    turns: list[dict] = []
    for line in lines:
        if "[3] asking the agent" in line:
            turns.append({})
            continue
        if not turns:
            continue
        for key, pattern in PATTERNS.items():
            found = pattern.search(line)
            if found:
                turns[-1][key] = found.group(1).replace(",", "")
    return turns


def table(turns: list[dict]) -> str:
    head = ["turn"] + [title for _, title in COLUMNS]
    rows = [[str(i)] + [t.get(key, "-") for key, _ in COLUMNS] for i, t in enumerate(turns, 1)]
    widths = [max(len(r[c]) for r in [head, *rows]) for c in range(len(head))]
    return "\n".join("  ".join(cell.rjust(w) for cell, w in zip(r, widths)) for r in [head, *rows])


if __name__ == "__main__":
    source = open(sys.argv[1], encoding="utf-8", errors="replace") if len(sys.argv) > 1 else sys.stdin
    found = parse(source)
    print(table(found) if found else "No turn found: is this the server's log, with INFO lines (WAXAL_LOG=INFO)?")
    print(f"{len(found)} turn(s). Directional, not a benchmark.")
