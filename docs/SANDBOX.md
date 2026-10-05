# Live test sandbox

A way to try WaxalAgent for real on your PC, in a container that cannot touch the rest of your system, and then from
your own WhatsApp. Two stages: first the web test page, then WhatsApp.

Nothing here could be run where this code was written (no Docker daemon, no Soynade or WhatsApp access): the compose file
was checked for syntax and the server was smoke-tested outside Docker with stand-in engines. Expect to fix small things on
the first run, and tell me what the logs say.

## Stage 1: the test page (Docker)

Needs Docker Desktop (WSL 2 on Windows). The image is small: no models.

```bash
git clone https://github.com/DemePS/WaxalAgent && cd WaxalAgent
cp example.env .env              # then edit: ANTHROPIC_API_KEY, WAXAL_TOKEN (any long random string)
docker compose up --build         # the stand-ins: starts in a minute, no models
```

Open **http://localhost:8000/?token=<your WAXAL_TOKEN>**. Type some text in the box (Wolof, or anything: the stand-in
translator only tags it) and send. You should see the agent's English answer come back. This checks the container, ffmpeg,
your Claude access and the agent. From another terminal: `uv run python scripts/smoke.py http://localhost:8000 <token>`.

Then Soynade's hosted API (nothing to download). First find out what your key can do: `uv run python scripts/check_api.py models`.

```bash
# in .env:  SOYNADE_API_KEY=...   WAXAL_STT=soynade  WAXAL_TTS=soynade
docker compose up --build
```

Open the page, hold **Hold to talk** and speak Wolof: you get the Wolof heard, the English the agent received, its answer,
the Wolof answer, and the spoken reply. Tick **Transcribe only** to test recognition alone.

- **Company proxy that re-signs HTTPS:** before `docker compose up --build`, copy the company root certificate (a `.crt`
  or `.pem` from IT) into `certs/`: the image installs it, so downloads trust it.
- Conversations are kept in `./data`; delete it to start over. Audio is not stored.

## Stage 2: your own WhatsApp (Meta's test number)

Every Meta developer app gets a free **test phone number** that can message up to five numbers you verify: no business
verification, no cost. Meta's console changes often: if a screen differs, follow Meta's current "WhatsApp Cloud API: get
started" guide for the same steps.

1. **Create the app.** developers.facebook.com > *My Apps* > *Create app* > type *Business* > add the **WhatsApp** product.
2. **API Setup page.** It shows the *test number*, its **Phone number ID**, and a **temporary access token** (valid 24 hours:
   fine for a test). Under *To*, add and verify your own WhatsApp number (Meta sends a code).
3. **App secret.** *App settings > Basic > App secret* (show it).
4. Put these in `.env`:
   ```
   WHATSAPP_TOKEN=<the temporary token>
   WHATSAPP_PHONE_NUMBER_ID=<Phone number ID>
   WHATSAPP_APP_SECRET=<App secret>
   WHATSAPP_VERIFY_TOKEN=<any string you invent>
   WAXAL_ALLOWED=<your number, digits only with the country code, e.g. 221771234567>
   WAXAL_EXTRA_ARGS=--whatsapp
   ```
5. **A public address for the webhook:**
   ```bash
   docker compose --profile tunnel up --build
   docker compose logs tunnel | grep trycloudflare      # prints https://<random>.trycloudflare.com
   ```
   (The address changes each time the tunnel restarts; that is fine for a test.)
6. **Webhook.** In the Meta console: *WhatsApp > Configuration > Webhook > Edit*: callback URL
   `https://<random>.trycloudflare.com/webhook`, verify token = your `WHATSAPP_VERIFY_TOKEN`. Meta calls the address once:
   if it saves, the handshake worked. Then *Manage* and subscribe to **messages**.
7. **Test.** From your verified number, message the test number: a voice note in Wolof. You should get a voice note back,
   and the same words as text. Check `docker compose logs -f waxal` while you do.

When the temporary token expires (24 h), make a new one on the API Setup page, update `.env` and `docker compose up -d`.
For a permanent setup use a system user's permanent token and your own business number.

## Troubleshooting

| What you see | Likely cause |
|---|---|
| Compose says `WAXAL_TOKEN` is missing | set it in `.env` |
| The page answers but "notes" mention `ANTHROPIC_API_KEY` | the key is missing or wrong in `.env` |
| A call fails with `CERTIFICATE_VERIFY_FAILED` | a proxy re-signs HTTPS: put the company root certificate in `certs/` and rebuild |
| Meta refuses the webhook address | the tunnel address changed, or `WHATSAPP_VERIFY_TOKEN` differs from the console |
| Messages arrive but no answer comes | your number is not in `WAXAL_ALLOWED` (digits only, country code first); check the log |
| 403 on the webhook in the log | `WHATSAPP_APP_SECRET` is wrong: the signature check fails |
| A voice note gets an apology | look for the error in `docker compose logs waxal` (ffmpeg, Soynade, or Claude) |
