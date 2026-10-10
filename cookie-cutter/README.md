# cookie-cutter

A template for a new app on the WaxalAgent library. IslamChat and SenAssurChat are the same thin layer: a package of three small files
and a page, the instructions, the skills, the documents and the settings. This creates that layer for a new app in one command.
Only the standard library is used (no `cookiecutter` package).

```bash
python cookie-cutter/new_app.py aidchat \
    --title "AidChat" \
    --purpose "Help people understand the rules for aid applications and what documents to bring." \
    --language fr \
    --domains "service-public.fr=Service Public" \
    --brand "#0b6e8a" \
    --git
```

It writes `../aidchat/` (next to the library; `--out` chooses another place) and prints the next steps:

```bash
cd ../aidchat
uv sync
cp example.env .env        # fill in the keys
uv run aidchat serve
```

## The parameters

| Option | What it sets | Default |
|---|---|---|
| `slug` (first argument) | the package, the command, the Docker image name: lower case letters and digits | required |
| `--title` | the name people see (page, instructions, README) | the slug, capitalised |
| `--description` | one sentence for `pyproject.toml` and the README | "<title>, built on the WaxalAgent library." |
| `--purpose` | what the agent is for, written in the instructions | a generic sentence |
| `--language` | `fr`, `en` or `wo` (`wo`: Wolof in and out, translated; otherwise no translation and `WAXAL_REPLY_LANGUAGE`) | `fr` |
| `--domains` | the trusted websites, `domain=Name, domain=Name`; empty: no browsing, no link | none |
| `--brand` | the accent colour of the page, `#rrggbb` | `#0a7d5a` |
| `--out` | where to create the app | `../<slug>` |
| `--git` | run `git init` | off |

## What it creates

| Path | What it is |
|---|---|
| `<slug>/` | the command (`cli.py`, 3 lines over the library's server) and the page `static/index.html` |
| `data/instructions/INSTRUCTIONS.md` | the instructions: purpose, sources in order (library first), how to answer by voice |
| `data/skills/answer-from-the-library/SKILL.md` | the base skill: search with a few words, open the passage, name the source, say when it is not there |
| `library/` | where the documents go (not committed) |
| `example.env`, `Dockerfile`, `docker-compose.yml`, `WHATSAPP.md`, `docs/SANDBOX.md` | the same as the other apps, with the name filled in |
| `tests/test_app.py` | page, endpoints, command and content fit the library |

Unlike the first two apps, `data/instructions/` and `data/skills/` are **committed**: only `data/users/` (conversations and memory) and
the documents are ignored, so a fresh clone has the instructions and the tests pass.

## Changing the template

The files are in `template/`. A `{{name}}` is replaced in the file contents and in the paths (the package folder is `{{app_slug}}/`).
The names are: `app_slug`, `app_title`, `description`, `purpose`, `language`, `brand_color`, `link_domains_line`, `language_settings`,
`sites_section`, `and_sites`. `tests/test_cookie_cutter.py` generates an app and fails on a placeholder that is not filled.
