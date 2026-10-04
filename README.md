# WaxalAgent

A Wolof voice agent. A person speaks Wolof (a voice note); the agent, which works in English, answers; the
answer is spoken back in Wolof.

```
Wolof voice -> [ASR] Wolof text -> [MT] English -> agent (CodeAgent) -> English -> [MT] Wolof -> [TTS] Wolof voice
```

Every stage is replaceable (`stt/`, `mt/`, `tts/`), and both languages are kept and shown so mistakes are visible.
The agent engine is [CodeAgent](https://github.com/DemePS/CodeAgent) (pinned in `pyproject.toml`).

Status: the pipeline, the agent per person, the test page, the WhatsApp webhook and the glue for the Wolof models are
written and tested **with stand-ins**. **Nothing has been run with the real Wolof models or against WhatsApp yet**: that
needs your PC (the models are downloaded from Hugging Face) and your Meta account. Steps below.

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

## The Wolof models (try them on your PC)

```bash
uv sync --extra models                     # torch + transformers: a large download
uv run python scripts/check_models.py      # English -> Wolof -> English, speaks check_1..3.wav, timings per stage
uv run python scripts/check_models.py my_recording.wav     # also what the recogniser hears in a Wolof recording
uv run waxal-agent serve --engines wolof   # the test page with the real models
```

| Stage | Default model (set another with the variable) | Note |
|---|---|---|
| Wolof speech -> text | `M9and2M/whisper-small-wolof` (`WAXAL_ASR_MODEL`) | Whisper-small fine-tuned on about 57 h of Wolof |
| Wolof <-> English | `facebook/nllb-200-distilled-600M` (`WAXAL_MT_MODEL`) | fine-tuned Wolof variants exist; weights are non-commercial (CC-BY-NC): check before charging for the service |
| Wolof text -> speech | `bilalfaye/speecht5_tts-wolof` (`WAXAL_TTS_MODEL`) | needs `WAXAL_TTS_SPEAKER`, a `.npy` speaker embedding of 512 numbers; judge the voice by listening |

I could not download or run these models where this code was written (no access to the model hub), so the engines were
only tested with the model libraries replaced. Expect to adjust them after the first real run, and expect a turn to take
seconds on a CPU (four model runs). Quality is the open question: ask a Wolof speaker to judge the translations and the voice
before anyone relies on it. Names, numbers, file names and technical words are the weak spots; the agent is told to keep
answers short and plain for that reason.

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

3. `uv run waxal-agent serve --engines wolof --whatsapp --host 0.0.0.0`, then in Meta's settings set the callback URL to
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

If downloading a model fails with `CERTIFICATE_VERIFY_FAILED`, a proxy on your network re-signs HTTPS with a company
certificate that Python does not know (your browser does). WaxalAgent turns on the operating system's certificate store
(through CodeAgent's `truststore`) before any download, so this should just work on a company Windows PC; set
`AGENT_SYSTEM_CERTS=0` to switch that off. If it still fails: set `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE` to the company
root certificate (a `.pem` from IT), or download the models on a machine without the proxy (`huggingface-cli download
<model>`), copy `~/.cache/huggingface` to this PC and run with `HF_HUB_OFFLINE=1`.
