# Test on WhatsApp

```bash
git clone https://github.com/DemePS/WaxalAgent && cd WaxalAgent
cp example.env .env
```

Edit `.env`. Set `DEVELOPER_MODE=0` (or delete the line) and fill in:

```
ANTHROPIC_API_KEY=...
ELEVENLABS_API_KEY=...
WAXAL_TOKEN=<any long random string>
WHATSAPP_TOKEN=...
WHATSAPP_PHONE_NUMBER_ID=...
WHATSAPP_APP_SECRET=...
WHATSAPP_VERIFY_TOKEN=<any string you invent>
WAXAL_ALLOWED=<your number, digits only with country code>
```

## Without Docker (uv)

```bash
uv sync
set -a; source .env; set +a
uv run waxal-agent serve --whatsapp --host 0.0.0.0 --port 8000
```

In a second terminal, a public address (needs `cloudflared`):

```bash
cloudflared tunnel --url http://localhost:8000
```

It prints `https://<random>.trycloudflare.com`. In Meta's console set the callback URL to
`https://<random>.trycloudflare.com/webhook` and the verify token to `WHATSAPP_VERIFY_TOKEN`, then subscribe to **messages**.
Send a Wolof voice note from your verified number.

## With Docker (the tunnel included)

```bash
# in .env also set:  WAXAL_EXTRA_ARGS=--whatsapp
docker compose --profile tunnel up --build
docker compose logs tunnel | grep trycloudflare
```

## Check the web page first (no WhatsApp)

Open `http://localhost:8000/?token=<WAXAL_TOKEN>`.
