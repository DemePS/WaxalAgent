"""The web server: a test page, and (milestone 3) the WhatsApp webhook."""

import base64
import hmac
import json
import logging
import os
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from .audio import AudioError
from .pipeline import Pipeline, TurnResult
from .soynade_api import SoynadeError
from .whatsapp import WhatsAppBot, signature_ok

log = logging.getLogger("waxal.server")

STATIC = Path(__file__).parent / "static"
MAX_RECORDING_BYTES = 10 * 1024 * 1024


class TextIn(BaseModel):
    text: str


def as_json(result: TurnResult) -> dict:
    return {"wolof": result.wolof, "english": result.english, "reply_english": result.reply_english,
            "reply_wolof": result.reply_wolof, "notes": result.notes,
            "audio": base64.b64encode(result.audio_wav).decode("ascii"), "audio_type": "audio/wav"}


def create_app(pipeline: Pipeline, token: str | None = None, bot: WhatsAppBot | None = None,
               test_page: bool = True) -> FastAPI:
    """`token`: when set (WAXAL_TOKEN), every /api call must send it in the X-Token header.
    `test_page`: False leaves only the WhatsApp webhook (a public server must not offer the test page)."""
    app = FastAPI(title="WaxalAgent", docs_url=None, redoc_url=None, openapi_url=None)

    def check(request: Request) -> None:
        if token and not hmac.compare_digest(request.headers.get("x-token", ""), token):
            raise HTTPException(403, "Forbidden")

    def user_of(request: Request) -> str:
        return request.headers.get("x-user", "test")[:64]

    def add_test_routes() -> None:
        @app.get("/api/health")
        def health(request: Request):
            check(request)
            return {"ok": True}

        @app.post("/api/turn")
        async def turn(request: Request):
            """The body is the recording (any audio format); the answer is JSON with both languages and the audio."""
            check(request)
            data = await request.body()
            if not data:
                raise HTTPException(400, "No audio received.")
            if len(data) > MAX_RECORDING_BYTES:
                raise HTTPException(413, "The recording is too long.")
            try:
                return as_json(pipeline.from_audio(user_of(request), data, speak=request.query_params.get("speak") != "0"))
            except AudioError as e:
                raise HTTPException(400, str(e))
            except Exception as e:  # a failing service (translation, recognition...): the page shows why, the log has the trace
                log.exception("The turn failed")
                raise HTTPException(502, f"{type(e).__name__}: {e}"[:500])

        @app.post("/api/transcribe")
        async def transcribe(request: Request):
            """Only the recogniser: a recording in, the Wolof words out (to try speech recognition on its own)."""
            check(request)
            data = await request.body()
            if not data:
                raise HTTPException(400, "No audio received.")
            if len(data) > MAX_RECORDING_BYTES:
                raise HTTPException(413, "The recording is too long.")
            try:
                return {"wolof": pipeline.transcribe(data)}
            except AudioError as e:
                raise HTTPException(400, str(e))
            except SoynadeError as e:
                raise HTTPException(502, str(e))

        @app.post("/api/text")
        async def text(request: Request, body: TextIn):
            """Wolof typed instead of spoken (for testing without a microphone)."""
            check(request)
            try:
                return as_json(pipeline.from_wolof(user_of(request), body.text, speak=request.query_params.get("speak") != "0"))
            except Exception as e:
                log.exception("The turn failed")
                raise HTTPException(502, f"{type(e).__name__}: {e}"[:500])

        @app.post("/api/speak")
        async def speak(request: Request, body: TextIn):
            """The voice of a Wolof text (the page asks for it after showing the texts)."""
            check(request)
            wav, notes = await run_in_threadpool(pipeline.speak_text, body.text)
            return {"audio": base64.b64encode(wav).decode("ascii"), "audio_type": "audio/wav", "notes": notes}

        @app.get("/")
        def index():
            return FileResponse(STATIC / "index.html")


    if bot is not None:
        @app.get("/webhook")
        def webhook_verify(request: Request):
            """Meta calls this once, when the webhook address is saved in its settings."""
            challenge = bot.verify(dict(request.query_params))
            if challenge is None:
                raise HTTPException(403, "Forbidden")
            return PlainTextResponse(challenge)

        @app.post("/webhook")
        async def webhook(request: Request, background: BackgroundTasks):
            """Answer 200 at once (Meta retries slow calls); the turn runs in the background."""
            body = await request.body()
            if not signature_ok(body, request.headers.get("x-hub-signature-256"), bot.config.app_secret):
                raise HTTPException(403, "Bad signature")
            try:
                payload = json.loads(body)
            except ValueError:
                raise HTTPException(400, "Not JSON")
            background.add_task(bot.handle, payload)
            return {"ok": True}

    if test_page:
        add_test_routes()

    return app


def token_from_env() -> str | None:
    return os.environ.get("WAXAL_TOKEN") or None
