# {{app_title}}

{{description}}

{{app_title}} is a thin layer over the **WaxalAgent library** (`../WaxalAgent`: the core `waxal_agent` and the web layer `waxal_server`).
All the code is there: the pipeline (speech recognition, translation, agent, voice), the per-person agent, S3 sync, the test page's server,
the WhatsApp webhook, links and browsing. **The library's README is the reference** for how all of that works and for every setting.
This folder only holds what makes the app its own:

| Path | What it is |
|---|---|
| `{{app_slug}}/` | the `{{app_slug}}` command (the library's server with this app's name) and the app's page, `static/index.html` |
| `data/instructions/INSTRUCTIONS.md` | the agent's general instructions |
| `data/skills/` | the skills, loaded on demand (`answer-from-the-library` is the base method) |
| `library/` | the documents the agent answers from (not committed) |
| `example.env` | the settings, with this app's values |
| `tests/test_app.py` | checks that the page, the command and the content fit the library |

## Try it

```bash
uv sync
cp example.env .env                       # every setting, with DEVELOPER_MODE=1; fill in the keys
set -a; source .env; set +a               # the server reads the environment, not the file
uv run {{app_slug}} serve                 # http://127.0.0.1:8000/?token=<WAXAL_TOKEN>
```

`DEVELOPER_MODE=1` keeps S3 and WhatsApp off, so only the test page is served. `WHATSAPP.md` has the commands to test on WhatsApp,
`docs/SANDBOX.md` the Docker sandbox.

## Tests

```bash
uv run python -m pytest
```
