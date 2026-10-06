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

**With S3 (production):** the person in charge puts the documents in a bucket (any S3 tool or the console works), and the server mirrors them to local folders.
- `s3://<bucket>/documents/...` is the library, the same for everybody (synced every `WAXAL_S3_INTERVAL` seconds, default 600).
- `s3://<bucket>/users/<phone number>/documents/...` are one person's own documents. They are fetched only when that person writes (at most every
  `WAXAL_S3_USER_TTL` seconds, default 60) into `data/users/<phone number>/documents/`, so only active people take disk space.
- Set `WAXAL_S3_BUCKET`; the credentials are the usual AWS ones (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, or a role); `WAXAL_S3_REGION`,
  `WAXAL_S3_ENDPOINT` (other S3-compatible stores), `WAXAL_S3_SHARED_PREFIX` and `WAXAL_S3_USERS_PREFIX` if the layout differs. Read access is enough.
- `DEVELOPER_MODE=1` switches S3 and the WhatsApp webhook off: the documents are the local folders and only the test page is served.

A changed file in S3 replaces the local copy, and a file removed from S3 is removed locally. Every file is copied as it is, whatever its kind; a file over
`WAXAL_MAX_UPLOAD_MB` (20) is skipped and logged. The agent reads PDF (`read_pdf`), Excel (`read_excel`), images (`view_image`), UTF-8 text (`read_file`) and, with WaxalAgent's own tools
(`waxal_agent/office_tools.py`, added with CodeAgent's `register_tool`), Word `.docx` (`read_word`) and PowerPoint `.pptx` (`read_powerpoint`) files.
Old `.doc` / `.ppt` files and other kinds are in the library but the agent cannot read them (save them as `.docx` / `.pptx` or PDF). Subfolders are kept. A failed S3 call changes nothing and is logged. Local files that are not in S3 are removed by the sync (use `DEVELOPER_MODE=1` to work with local files).

**Without S3:** an administrator adds documents by copying them into the library folder, or by sending a document or photo on WhatsApp
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

## Shipping a deployment with its documents baked in

Put the deployment's documents (the domain: finance, medicine...) in `library/` (or any folder), then build:

```bash
docker compose build                       # uses ./library
LIBRARY=customers/acme/docs docker compose build   # or another folder
```

The documents are copied into the image at `/app/library` and `WAXAL_DOCUMENTS` points there, so the customer receives
one private image: no source, no documents to copy. Each person's own documents and memory stay in the mounted `data/`
volume. `library/` is git-ignored so customer documents are never committed.

## Streaming the voice

`POST /api/speak/stream` with `{"text": "<Wolof>"}` (and the `X-Token` header) sends the voice while ElevenLabs makes it
(`audio/mpeg`, `ELEVENLABS_STREAM_FORMAT`, default `mp3_44100_64`), so a client can start playing at once. A speaker that cannot
stream sends the whole WAV. When no voice can be made, the answer is a 502 with the reason, before any audio. `/api/speak`
(the whole clip as base64 WAV) is unchanged, and so is the WhatsApp voice note, which needs a finished file.

## Links

The agent can show the person a link (`share_link`), for example to the insurance regulator's site. The link is displayed on the page and
sent as text under the answer on WhatsApp, and never spoken. Only `https` addresses on the sites of `WAXAL_LINK_DOMAINS` (a site and its
subdomains, e.g. `renassur.sn`) are accepted; a refusal tells the agent why. When it is not set, no link is shared. The agent can also use
`web_search` (Anthropic's hosted search, `AGENT_WEB_SEARCH=off` to disable it) to find the page. No link to the library's files is offered.

## INSTRUCTIONS.md: general instructions, apart from the documents

Put a file named `INSTRUCTIONS.md` in `data/instructions/` (`WAXAL_INSTRUCTIONS_DIR`, or `--instructions`). The agent lists that folder at the start of a
turn, reads the file with `read_file` when it is there, and follows it: what the documents are, how to use them and the tasks it has to do. It is
the same for every person, and it is kept apart from the library, which holds only the knowledge the agent answers from. The folder is read-only for
the agent and is the only part of `data/` it can open (the people's folders and conversations are not). No code is involved, so a customer can
write their own: `docs/INSTRUCTIONS.example.md` is an example (two documents, and a link to a partner). With Docker, `data/` is the mounted volume,
so edit the file there.

## Streaming a turn

`POST /api/turn/stream` (the recording as the body) and `POST /api/text/stream` (`{"text": "<Wolof>"}`) answer with JSON lines, each sent as soon as it
exists: `heard` (what was understood), `answer` (the agent's answer and the links it shared), then for each piece of the answer a `text` (its Wolof)
followed by the `audio` chunks of its voice, and `done` with the notes (`note` and `error` events tell what went wrong). After the agent has answered,
the answer is cut into small pieces that are all translated at the same time; the first piece is spoken as soon as it is translated, while the others
still are, and the voice of each piece is streamed while ElevenLabs makes it (`audio/mpeg`; a speaker that cannot stream sends one WAV clip per piece).
The test page uses these routes. `/api/turn` and `/api/text` (one JSON answer) are unchanged, and so is WhatsApp, which needs finished files; the
pieces of its answer are translated at the same time too.
