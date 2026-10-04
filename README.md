# WaxalAgent

A Wolof voice agent. A person speaks Wolof (a voice note); the agent, which works in English, answers; the
answer is spoken back in Wolof.

```
Wolof voice -> [ASR] Wolof text -> [MT] English -> agent (CodeAgent) -> English -> [MT] Wolof -> [TTS] Wolof voice
```

Every stage is replaceable (`stt/`, `mt/`, `tts/`), and both languages are kept and shown so mistakes are visible.
The agent engine is [CodeAgent](https://github.com/DemePS/CodeAgent) (pinned in `pyproject.toml`).

Status: **milestone 1** (the pipeline, the agent per person, the test page, with stand-in engines). The Wolof models
(milestone 2) and WhatsApp (milestone 3) are not done yet.

## Try it

```bash
uv sync
export ANTHROPIC_API_KEY=sk-ant-...      # or the Foundry variables, see the CodeAgent README
uv run waxal-agent serve                  # http://127.0.0.1:8000
```

With the stand-in engines nothing is really recognised or translated: "hearing" returns a fixed Wolof sentence and
translation tags the text `[en]` / `[wo]`. The page shows the whole turn, so the plumbing (recording, agent, audio
back) can be checked before the real models exist. ffmpeg must be installed (it converts the recordings).

Set `WAXAL_TOKEN` to require a token (header `X-Token`, or `?token=` in the page address) when the server is reachable
from other machines.

## Safety (a public channel)

- The agent gets read-only tools (`agent.py` `TOOLS`): it cannot change or delete files, run programs or browse.
- One folder and one saved conversation per person (`data/users/<id>`).
- Nothing is approved by voice: a request that would need approval is refused and noted.
- CodeAgent keeps its state in the process, so turns run one at a time under a lock; run several processes for more.

## Tests

```bash
uv run pytest
```
