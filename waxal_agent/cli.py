"""waxal-agent serve: start the test page (and later the WhatsApp webhook)."""

import argparse
import os
import sys
from pathlib import Path


def build_pipeline(engines: str, data: str, documents: str | None = None, refresh=None):
    from .agent import AgentTurns
    from .engines import build_engines
    from .pipeline import Pipeline
    listener, translator, speaker = build_engines(engines)
    workers = int(os.environ.get("WAXAL_WORKERS") or 4)
    if workers > 1:  # turns of different people run in parallel, in separate processes
        from .agent_pool import AgentPool
        return Pipeline(listener, translator, speaker, AgentPool(workers, data, documents, refresh))
    return Pipeline(listener, translator, speaker, AgentTurns(data, documents=documents, refresh=refresh))


def main() -> None:
    parser = argparse.ArgumentParser(prog="waxal-agent", description="A Wolof voice agent.")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Start the web server with the test page.")
    serve.add_argument("--engines", default=None, help="hosted (recognition, translation, voice: ElevenLabs for recognition and voice, Claude for translation; WAXAL_STT, WAXAL_MT and WAXAL_TTS change each one; the default when SOYNADE_API_KEY or ELEVENLABS_API_KEY is set), soynade-asr (only recognition is real) or fake (stand-ins, the default without a key).")
    serve.add_argument("--whatsapp", action="store_true",
                       help="Answer WhatsApp voice notes at /webhook (needs the WHATSAPP_* variables, see README).")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--documents", default=os.environ.get("WAXAL_DOCUMENTS") or "data/documents",
                       help="The library: the documents shared by every person (an administrator adds them). WAXAL_DOCUMENTS.")
    serve.add_argument("--data", default="data/users", help="Where each person's folder and conversation are kept.")
    args = parser.parse_args()
    import logging

    import uvicorn

    logging.basicConfig(level=os.environ.get("WAXAL_LOG", "INFO").upper(), format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per HTTP request adds nothing here
    from . import certs
    from . import maintenance
    maintenance.start()  # old conversations and notes: once now, then daily
    certs.trust_system_certificates()  # a company proxy re-signs HTTPS (models, Meta)
    from .server import create_app, token_from_env
    engines = args.engines or ("hosted" if os.environ.get("SOYNADE_API_KEY") or os.environ.get("ELEVENLABS_API_KEY") else "fake")
    print(f"Engines: {engines}" + (" (stand-ins: no Wolof is really heard, translated or spoken; set SOYNADE_API_KEY or ELEVENLABS_API_KEY)" if engines == "fake" else ""),
          file=sys.stderr)
    from .language import REPLY_LANGUAGE
    print(f"The agent works and answers in: {REPLY_LANGUAGE}" + ("" if REPLY_LANGUAGE == "wo" else " (translated into Wolof by Soynade)"),
          file=sys.stderr)
    developer = os.environ.get("DEVELOPER_MODE", "").lower() in ("1", "true", "yes", "on")
    s3 = None
    if os.environ.get("WAXAL_S3_BUCKET") and not developer:
        from .s3_sync import S3Documents, s3_client
        s3 = S3Documents(s3_client(), os.environ["WAXAL_S3_BUCKET"], os.environ.get("WAXAL_S3_SHARED_PREFIX") or "documents/",
                         os.environ.get("WAXAL_S3_USERS_PREFIX") or "users/")
        s3.start(Path(args.documents))
        print(f"The documents come from S3 (bucket {s3.bucket}); the library is synced every {s3.interval:.0f} s.", file=sys.stderr)
    elif os.environ.get("WAXAL_S3_BUCKET"):
        print("DEVELOPER_MODE: S3 is off, the documents are read from the local folders.", file=sys.stderr)
    pipeline = build_pipeline(engines, args.data, args.documents, refresh=s3.refresh_user if s3 else None)
    bot = None
    if args.whatsapp and developer:
        print("DEVELOPER_MODE: WhatsApp is off, only the test page is served.", file=sys.stderr)
    elif args.whatsapp:
        from .whatsapp import WhatsAppBot, WhatsAppClient, WhatsAppConfig
        config = WhatsAppConfig.from_env()
        bot = WhatsAppBot(pipeline, WhatsAppClient(config), config)
        if not config.allowed:
            print("Warning: WAXAL_ALLOWED is empty: nobody can use the agent yet.", file=sys.stderr)
    # With WhatsApp on a public server, the test page is only offered when a token protects it.
    from .files import Library
    user_files = Library(args.documents)
    if bot is not None:
        bot.files = user_files
    app = create_app(pipeline, token_from_env(), bot, test_page=(bot is None or token_from_env() is not None), files=user_files)
    if not os.environ.get("WAXAL_TOKEN") and args.host not in ("127.0.0.1", "localhost"):
        print("Warning: listening beyond this PC without WAXAL_TOKEN set: anyone who can reach it can use the agent.",
              file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port)
