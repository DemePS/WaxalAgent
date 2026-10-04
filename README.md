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

## Soynade's hosted API (no model to host)

Soynade offers a hosted, OpenAI-compatible API (`https://api.soynade.ai/openai/v1`, key in `SOYNADE_API_KEY`). **Speech
recognition is wired** (`stt/soynade_api.py`, model `oolel-speech-v1`, from Soynade's quickstart): try it on a Wolof
recording with `uv run python scripts/check_api.py recording.wav`. Translation and speech output through the API are **not
wired yet**: they wait for the corresponding pages of Soynade's reference. Until then a full turn needs the model-based
engines below. Everything you say or hear goes to Soynade when you use the API: say so in your terms.

## The Wolof models (try them on your PC)

```bash
uv sync --extra models                          # torch + transformers + the TTS libraries: a large download
uv run python scripts/check_models.py           # Soynade engines: English -> Wolof -> English, speaks check_1..3.wav, timings
uv run python scripts/check_models.py soynade my_recording.wav     # also what the recogniser hears in a Wolof recording
uv run waxal-agent serve --engines soynade      # the test page with the real models
```

Two sets of engines (`--engines`): **`soynade`** (chosen) and `wolof` (an earlier set kept for comparison: a Whisper Wolof
model, NLLB-200, SpeechT5).

| Stage | `soynade` engine (model; variable to change it) | Notes |
|---|---|---|
| Wolof speech -> text | `soynade-research/Wolof-HuBERT-CTC` (`WAXAL_ASR_MODEL`) | a HuBERT CTC model, run through transformers' ASR pipeline |
| Wolof <-> English | `soynade-research/Oolel-Small-v0.1` (`WAXAL_MT_MODEL`) | a Qwen 2.5 chat model asked "Translate to Wolof the following sentence" (the prompt of Soynade's own translation pipeline); the Wolof -> English prompt is my assumption: change it with `WAXAL_MT_PROMPT_WO_EN` if the model card says otherwise. Greedy decoding |
| Wolof text -> speech | `soynade-research/Oolel-Voices` (`WAXAL_TTS_MODEL`) | clones the style of a short reference recording: `WAXAL_TTS_VOICE=<a short .wav>`; `WAXAL_TTS_CFG`, `WAXAL_TTS_EXAGGERATION`, `WAXAL_TTS_TEMPERATURE` tune it (defaults 0.5, 0.2, 0.3) |

**What is verified and what is not.** I could not open Hugging Face or soynade.ai where this was written, only search
results and Soynade's public GitHub pages. From those: the three model repositories exist, the translation prompt and
model id of their pipeline, and Oolel-Voices' loading and `generate` arguments (`snapshot_download`, then
`AutoModel.from_pretrained(..., trust_remote_code=True)`, then `model.generate(text, audio_prompt_path=, cfg_weight=,
exaggeration=, temperature=)`). Not verified: the exact model ids (Oolel-Small vs Oolel-v0.1, the ASR model's loading
details), the wolof -> English prompt, the sample rate and output type of Oolel-Voices, and whether it works without a
voice prompt. The engines are tested with the libraries replaced, never with the real models: expect to adjust them after
the first run, and send me what `check_models.py` prints.

**Licences, before anyone is charged or served publicly.** `trust_remote_code=True` runs code published in the Oolel-Voices
repository. Soynade's translation pipeline is AGPL-3.0 (offer your source to the users of a network service you build on
it), and each model has its own licence: read the three model cards. `transformers` and `diffusers` are pinned to the
versions Oolel-Voices asks for.

Quality is the open question: ask a Wolof speaker to judge the translations and the voice. Names, numbers, file names and
technical words are the weak spots; the agent is told to keep answers short and plain for that reason. A turn is four
model runs: expect seconds on a CPU, and Oolel is a language model, so the translation step is the slowest.

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

3. `uv run waxal-agent serve --engines soynade --whatsapp --host 0.0.0.0`, then in Meta's settings set the callback URL to
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
