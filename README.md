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

## The library: documents shared by everybody

All the documents are common to all users: they live in one library folder (`data/documents`, `WAXAL_DOCUMENTS` or `--documents`),
and the agent reads them, read-only, for every person. Each person's own folder (`data/users/<number>/`) only holds their
conversation. Nobody but an administrator adds documents.

**With Google Drive (recommended):** the administrators add, replace and remove documents in one Drive folder, and the server mirrors it.
1. In Google Cloud: create a project, enable the **Google Drive API**, create a **service account** and download its JSON key.
2. In Drive: share the documents folder with the service account's e-mail address (viewer is enough).
3. Set `WAXAL_DRIVE_FOLDER` (the folder id: the last part of its address) and `WAXAL_DRIVE_CREDENTIALS` (the key file's path; or
   `WAXAL_DRIVE_CREDENTIALS_JSON` with the JSON itself). `WAXAL_DRIVE_INTERVAL` (seconds, default 600) is the time between syncs.

A change in Drive replaces the local file, and a file removed or trashed in Drive is removed locally. The files are copied as they are; a kind the agent
cannot read or a file over `WAXAL_MAX_UPLOAD_MB` (20) is skipped and logged. Only the files directly in the folder are used. A failed Drive call changes nothing and is logged.
Files that the sync did not add are never touched.

**Without Drive:** an administrator adds documents on the test page (protected by `WAXAL_TOKEN`), or by sending a document or photo on WhatsApp
from a number in `WAXAL_ADMINS` (comma-separated digits); never overwritten (`report (2).pdf`); 1000 files at most.

## ElevenLabs (recognition and voice)

Instead of Soynade (for example when its credits are used up): `ELEVENLABS_API_KEY`, then `WAXAL_STT=elevenlabs` (Wolof speech to
Wolof text, translated to English by Claude) and/or `WAXAL_TTS=elevenlabs` (the Wolof voice, model `eleven_v4`, voice
`ELEVENLABS_VOICE_ID`). Try each on its own first: `uv run python scripts/check_api.py eleven-speak "Nanga def"` and
`eleven-listen recording.wav`. If ElevenLabs rejects a language field, the error says so: set `ELEVENLABS_TTS_LANGUAGE` or
`ELEVENLABS_STT_LANGUAGE` (an empty value leaves the field out).

## Live sandbox (Docker + your own WhatsApp)

`docker compose up --build` runs the server in a container (test page on localhost), and `docs/SANDBOX.md` walks through the
real models and a WhatsApp test with Meta's free test number and a temporary public address. Start there.

## Soynade's hosted API (nothing is hosted here)

Translation is done by Claude by default (`WAXAL_MT=soynade` uses Soynade's translation route instead). Speech recognition and the Wolof voice go through Soynade's own API routes (`https://api.soynade.ai/v1`, your key in `SOYNADE_API_KEY`,
created in their console), called directly over HTTPS: no chat client, no model downloaded or run here.

| Stage | Route and model | Status |
|---|---|---|
| **Wolof speech -> English, one call** | `POST /v1/audio/translations` | **exact** (Soynade's reference): multipart `file`, `source_language=wo`, `target_language=en`, `response_format=json`, `temperature`. This is the default for voice notes: recognition and incoming translation in one call (`WAXAL_DIRECT=off` for the two-step path, `WAXAL_SHOW_WOLOF=1` to also show the Wolof heard, one more call) |
| Wolof speech -> Wolof text | `POST /v1/audio/transcriptions`, `oolel-speech-v1` | multipart upload (file, model); used by "Transcribe only" and for typed-text turns |
| English -> Wolof text (the reply) | `POST /v1/translations`, `oolel-speech-v1` | JSON; field names not in what I could read: likely shapes (`text` / `input` with `source_language` / `target_language`) are tried until one is accepted |
| Wolof text -> speech | `POST /v1/text-to-speech`, Oolel-Voices, default voice | **exact** (from Soynade's reference): JSON `{text, language: "wo", output_format: "wav", exaggeration, temperature, cfg_weight, seed}`; the answer is the WAV file |

For recognition and translation the request fields come from no page I could read, so a rejected shape shows **Soynade's own error message**: send it to me
(or the field list from their reference) and I correct it. Try one step at a time:

```bash
export SOYNADE_API_KEY=...
uv run python scripts/check_api.py understand recording.wav    # Wolof speech -> English (one call)
uv run python scripts/check_api.py listen recording.wav        # Wolof speech -> Wolof text
uv run python scripts/check_api.py translate en wo "Hello"     # then: translate wo en "..."
uv run python scripts/check_api.py speak "Naka nga def?"       # writes speech.wav: play it
uv run waxal-agent serve --engines soynade                     # the whole turn, on the test page
```

If audio output is not offered for your key ("Only text output is supported during launch"), a reply stays text only and the
API is not asked again for ten minutes (`SOYNADE_TTS=off` stops asking). Rate limits (HTTP 429) are waited out as the server
says; each turn is about four calls. Everything people say, and every reply, goes to Soynade: say so in your terms.
`--engines soynade-asr` uses only their recognition (the rest are stand-ins). Other voices: `WAXAL_TTS=huggingface`
(`HF_TOKEN`, MMS Wolof, non-commercial licence) or `WAXAL_TTS=oolel-demo` (Soynade's public demo Space, `uv sync --extra demo`).

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
