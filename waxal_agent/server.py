"""The web server: a test page, and (milestone 3) the WhatsApp webhook."""

import base64
import hmac
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .audio import AudioError
from .pipeline import Pipeline, TurnResult

STATIC = Path(__file__).parent / "static"
MAX_RECORDING_BYTES = 10 * 1024 * 1024


class TextIn(BaseModel):
    text: str


def as_json(result: TurnResult) -> dict:
    return {"wolof": result.wolof, "english": result.english, "reply_english": result.reply_english,
            "reply_wolof": result.reply_wolof, "notes": result.notes,
            "audio": base64.b64encode(result.audio_wav).decode("ascii"), "audio_type": "audio/wav"}


def create_app(pipeline: Pipeline, token: str | None = None) -> FastAPI:
    """`token`: when set (WAXAL_TOKEN), every /api call must send it in the X-Token header."""
    app = FastAPI(title="WaxalAgent", docs_url=None, redoc_url=None, openapi_url=None)

    def check(request: Request) -> None:
        if token and not hmac.compare_digest(request.headers.get("x-token", ""), token):
            raise HTTPException(403, "Forbidden")

    def user_of(request: Request) -> str:
        return request.headers.get("x-user", "test")[:64]

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
            return as_json(pipeline.from_audio(user_of(request), data))
        except AudioError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/text")
    async def text(request: Request, body: TextIn):
        """Wolof typed instead of spoken (for testing without a microphone)."""
        check(request)
        return as_json(pipeline.from_wolof(user_of(request), body.text))

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    return app


def token_from_env() -> str | None:
    return os.environ.get("WAXAL_TOKEN") or None
