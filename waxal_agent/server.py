"""The web server: a test page, and (milestone 3) the WhatsApp webhook."""

import base64
import hmac
import json
import logging
import os
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from .audio import AudioError
from .files import MAX_BYTES, FileRefused, Library
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
            "reply_wolof": result.reply_wolof, "notes": result.notes, "links": result.links,
            "audio": base64.b64encode(result.audio_wav).decode("ascii"), "audio_type": "audio/wav"}


def create_app(pipeline: Pipeline, token: str | None = None, bot: WhatsAppBot | None = None,
               test_page: bool = True, files: Library | None = None) -> FastAPI:
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

        def ndjson(user_id: str, result: TurnResult):
            """The rest of the turn as a stream of JSON lines (pipeline.stream_turn): texts and voice go out while the next pieces are made."""
            return StreamingResponse((json.dumps(event, ensure_ascii=False) + "\n" for event in pipeline.stream_turn(user_id, result)),
                                     media_type="application/x-ndjson", headers={"cache-control": "no-store"})

        @app.post("/api/turn/stream")
        async def turn_stream(request: Request):
            """Like /api/turn, but streamed: the recording is understood first (errors are a normal 4xx/5xx), then JSON lines."""
            check(request)
            data = await request.body()
            if not data:
                raise HTTPException(400, "No audio received.")
            if len(data) > MAX_RECORDING_BYTES:
                raise HTTPException(413, "The recording is too long.")
            try:
                result = await run_in_threadpool(pipeline.hear_audio, data)
            except AudioError as e:
                raise HTTPException(400, str(e))
            except Exception as e:
                log.exception("The turn failed")
                raise HTTPException(502, f"{type(e).__name__}: {e}"[:500])
            return ndjson(user_of(request), result)

        @app.post("/api/text/stream")
        async def text_stream(request: Request, body: TextIn):
            """Like /api/text, but streamed (see /api/turn/stream)."""
            check(request)
            try:
                result = await run_in_threadpool(pipeline.hear_wolof, body.text)
            except Exception as e:
                log.exception("The turn failed")
                raise HTTPException(502, f"{type(e).__name__}: {e}"[:500])
            return ndjson(user_of(request), result)

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

        @app.post("/api/speak/stream")
        async def speak_stream(request: Request, body: TextIn):
            """The voice of a Wolof text, sent while it is made (audio/mpeg with ElevenLabs, WAV with a speaker that cannot stream).
            When no voice can be made: 502 and the reason, before any audio."""
            check(request)
            media, audio_bytes, notes = await run_in_threadpool(pipeline.speak_stream, body.text)
            if not media:
                raise HTTPException(502, "; ".join(notes) or "No voice.")
            return StreamingResponse(audio_bytes, media_type=media)

        @app.post("/api/stop")
        def stop(request: Request):
            """Stop the agent's running turn (the page's Stop button)."""
            check(request)
            return {"stopped": pipeline.stop()}

        @app.get("/api/files")
        def list_files(request: Request):
            check(request)
            return {"files": files.list() if files else [], "enabled": files is not None}

        @app.post("/api/files")
        async def upload_file(request: Request, name: str):
            """The body is the file, `name` its name: it lands in the person's folder, where the agent reads it."""
            check(request)
            if files is None:
                raise HTTPException(404, "Uploads are not enabled.")
            data = await request.body()
            if len(data) > MAX_BYTES:
                raise HTTPException(413, "The file is too big.")
            try:
                return {"name": files.save(name, data), "files": files.list()}
            except FileRefused as e:
                raise HTTPException(400, str(e))

        @app.delete("/api/files")
        def delete_file(request: Request, name: str):
            check(request)
            if files is None:
                raise HTTPException(404, "Uploads are not enabled.")
            try:
                files.delete(name)
            except FileRefused as e:
                raise HTTPException(400, str(e))
            return {"files": files.list()}

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
