# TODO

## Tests out of sync with the refactor
- `uv run pytest`: 197 passed, 13 failed, 18 errors. The failures are tests that still use names the refactor removed:
  `SYSTEM_PROMPT`, `SPOKEN` and `CONCISE` imported from `waxal_agent.agent` (now `build_system_prompt()` and
  `concise_notice()`), and `pipeline.REPLY_LANGUAGE` (`tests/test_stream.py`, `tests/test_no_translation.py`).
- Update those tests to the new API.

## Agent pool
- With `WAXAL_WORKERS` > 1 the pool gives a turn to the lowest free worker, which may still be saving the previous
  turn's notes (they are saved in the background now): prefer a worker that is really idle.

## Settings
- Consider `AGENT_MEMORY_MODEL=claude-haiku-5-5`: the notes saved after each answer would cost far less.
- `.env` still has an unused `HF_TOKEN=` line, and `WAXAL_LINK_DOMAINS=renassur.sn,example.sn` from an earlier test.
- `AGENT_CACHE_TTL=1h` only if real WhatsApp use shows pauses longer than 5 minutes between messages.

## DeepSeek (when the key is available)
- Put `DEEPSEEK_API_KEY` in `.env` and run the two-question cache test on `deepseek-flash`; add it to the cost table
  (Claude Sonnet 5 with the new caching: about $0.034 per call after the first, on a 110K-token conversation).
- Check: answer quality in French, tool use, and whether `search_pdf` + text-mode `read_pdf` are enough without PDF documents.

## Untracked files
- `docs/claude-code-prompt.md`, `docs/wolof-data-landscape.html`, `eval/`, `out.wav`, `recording.ogx`, `speech.wav`:
  commit, move or delete.
