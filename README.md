# WaxalAgent

A Wolof voice agent. A person speaks Wolof (a voice note); the agent, which works in English, answers; the
answer is spoken back in Wolof.

```
Wolof voice -> [ASR] Wolof text -> [MT] English -> agent (CodeAgent) -> English -> [MT] Wolof -> [TTS] Wolof voice
```

Every stage is replaceable (`stt/`, `mt/`, `tts/`), and both languages are kept and shown so mistakes are visible.
The agent engine is [CodeAgent](https://github.com/DemePS/CodeAgent) (pinned in `pyproject.toml`).

Status: the pipeline, the agent per person, the test page, the WhatsApp webhook and Soynade's speech recognition are written
and tested **with stand-ins and recorded responses**. Nothing has been run against Soynade's real service or WhatsApp yet:
that needs your keys. Translation and speech output through Soynade's API are not wired yet. Steps below.

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

## Live sandbox (Docker + your own WhatsApp)

`docker compose up --build` runs the server in a container (test page on localhost), and `docs/SANDBOX.md` walks through the
real models and a WhatsApp test with Meta's free test number and a temporary public address. Start there.

## Soynade's hosted API (nothing is hosted here)

All speech and translation go through Soynade's hosted, OpenAI-compatible API (`https://api.soynade.ai/openai/v1`, your key
in `SOYNADE_API_KEY`, created in their console). **No model is downloaded or run by this project.**

| Stage | Status |
|---|---|
| Wolof speech -> text | wired: `stt/soynade_api.py`, model `oolel-speech-v1` (from Soynade's quickstart) |
| Wolof <-> English | wired and **tested live** ("How are you?" -> "Naka nga def?"): `mt/soynade_api.py` asks a chat model "Translate to Wolof the following sentence" (their own pipeline's prompt). The model id is `SOYNADE_MT_MODEL`, else found in the model list |
| Wolof text -> speech | **not available from Soynade yet**: their API answers "Only text output is supported during launch". `tts/soynade_api.py` is ready (chat route with audio output, then `audio/speech`) and a reply stays **text only** (voice note skipped, text message sent) until Soynade turns audio output on; it asks again every ten minutes. `SOYNADE_TTS=off` stops asking |

The last two rows are not confirmed by any Soynade page I could read (their reference is blocked where this was written).
Find out what works for your key, one step at a time:

```bash
export SOYNADE_API_KEY=...
uv run python scripts/check_api.py models                      # the models your key can use: set SOYNADE_*_MODEL from this
uv run python scripts/check_api.py listen recording.wav        # Wolof speech -> text
uv run python scripts/check_api.py translate en wo "Hello"     # then: translate wo en "..."
uv run python scripts/check_api.py speak "Nanga def"           # writes speech.wav: play it
uv run waxal-agent serve --engines soynade                     # the whole turn through the API, on the test page
```

If a step fails, the message shows Soynade's own error: send it to me, together with the model list, and I will adjust.
`--engines soynade-asr` uses only their recognition (the rest are stand-ins).

Everything people say, and every reply, goes to Soynade when you use the API: say so in your terms, and read their terms
and prices (each turn is several API calls).

## WhatsApp

Uses Meta's WhatsApp Business Cloud API: a business account, a phone number, and a public HTTPS address for the webhook
(a tunnel such as `cloudflared tunnel` is enough to try it). Meta's console has its own steps; the parts that concern this code:

1. In your Meta app, add the WhatsApp product, get a phone number id and a permanent access token.
2. Set the environment (a `.env` is not read: export them, or use your host's secret store; never commit them):

   | Variable | Meaning |
   |---|---|
   | `WHATSAPP_TOKEN` | the access token |
   | `WHATSAPP_PHONE_NUMBER_ID` | the id of the business number |
   | `WHATSAPP_VERIFY_TOKEN` | any secret string, also typed into Meta's webhook settings |
   | `WHATSAPP_APP_SECRET` | the app's secret: every webhook call's signature is checked with it |
   | `WAXAL_ALLOWED` | phone numbers allowed to use the agent, digits, comma-separated. **Empty: nobody** |
   | `WHATSAPP_GRAPH_VERSION` | optional, default `v21.0` (check Meta's current version) |

3. `uv run waxal-agent serve --engines <engines> --whatsapp --host 0.0.0.0`, then in Meta's settings set the callback URL to
   `https://<your address>/webhook` with the verify token, and subscribe to the `messages` field.
4. Send a voice note from an allowed number. You get a voice note back and the same words as text.

Behaviour: a number that is not allowed gets no answer at all; the same message delivered twice is answered once; a
failing turn answers with a short apology; images and other kinds of message get a one-line explanation. The test page is
not offered on a public server unless `WAXAL_TOKEN` is set. Voice notes are converted and discarded: only the agent's
conversation (text) is kept in `data/users/`. Outside Meta's 24-hour window after the person's last message, only approved
template messages can be sent: this code only ever answers messages, so it stays inside that window.

## Safety (a public channel)

- The agent gets read-only tools (`agent.py` `TOOLS`): it cannot change or delete files, run programs or browse.
- One folder and one saved conversation per person (`data/users/<id>`).
- Nothing is approved by voice: a request that would need approval is refused and noted.
- Only numbers in `WAXAL_ALLOWED` are served; the webhook refuses calls without a valid signature.
- CodeAgent keeps its state in the process, so turns run one at a time under a lock; run several processes for more.

## Tests

```bash
uv run pytest
```

## Behind a company proxy

If a call fails with `CERTIFICATE_VERIFY_FAILED`, a proxy on your network re-signs HTTPS with a company certificate that
Python does not know (your browser does). WaxalAgent turns on the operating system's certificate store (through CodeAgent's
`truststore`) at startup, so this should just work on a company Windows PC; set `AGENT_SYSTEM_CERTS=0` to switch that off.
If it still fails, set `SSL_CERT_FILE` to the company root certificate (a `.pem` from IT). In Docker, put it in `certs/`.
