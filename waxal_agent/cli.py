"""waxal-agent serve: start the test page (and later the WhatsApp webhook)."""

import argparse
import os
import sys
from pathlib import Path


def build_pipeline(data: str, documents: str | None = None, refresh=None, instructions: str | None = None, skills: str | None = None):
    from .agent import AgentTurns
    from .engines import build_engines
    from .pipeline import Pipeline
    listener, translator, speaker = build_engines("hosted")
    return Pipeline(listener, translator, speaker, AgentTurns(data, documents=documents, refresh=refresh, instructions=instructions, skills=skills))


def quiet_loggers() -> None:
    """Libraries whose log lines only pollute the terminal: httpx logs one line per HTTP request, azure.identity its credential
    probing, pypdf a warning per font and page while it reads a PDF (a long PDF prints thousands of them)."""
    import logging
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("pypdf").setLevel(logging.ERROR)


def load_env() -> None:
    """The settings of a .env file, before anything reads os.environ (the engines, the documents folder...): the first .env found from
    the folder you run in upwards, then ~/.coding-agent/.env, as CodeAgent does. A variable already set in the environment wins."""
    from pathlib import Path

    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv(usecwd=True))
    load_dotenv(Path(os.environ.get("HOME") or Path.home()).expanduser() / ".coding-agent" / ".env")


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(prog="waxal-agent", description="A Wolof voice agent.")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Start the web server with the test page.")
    serve.add_argument("--whatsapp", action="store_true",
                       help="Answer WhatsApp voice notes at /webhook (needs the WHATSAPP_* variables, see README).")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--documents", default=os.environ.get("WAXAL_DOCUMENTS") or "data/documents",
                       help="The library: the documents shared by every person (an administrator adds them). WAXAL_DOCUMENTS.")
    serve.add_argument("--instructions", default=os.environ.get("WAXAL_INSTRUCTIONS_DIR") or "data/instructions",
                       help="The folder with INSTRUCTIONS.md: general instructions for the agent, apart from the documents. WAXAL_INSTRUCTIONS_DIR.")
    serve.add_argument("--skills", default=os.environ.get("WAXAL_SKILLS_DIR") or "data/skills",
                       help="The folder of the agent's skills (one folder with a SKILL.md each), the same for every person. WAXAL_SKILLS_DIR.")
    serve.add_argument("--data", default="data/users", help="Where each person's folder and conversation are kept.")
    args = parser.parse_args()
    import logging

    import uvicorn

    logging.basicConfig(level=os.environ.get("WAXAL_LOG", "INFO").upper(), format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    quiet_loggers()
    from . import certs
    from . import maintenance
    maintenance.start()  # old conversations and notes: once now, then daily
    certs.trust_system_certificates()  # a company proxy re-signs HTTPS (models, Meta)
    from .server import create_app, token_from_env
    from .engines import describe_engines
    used = describe_engines("hosted")
    print(f"Engines: recognition: {used['stt']}, translation: {used['mt']}, voice: {used['tts']}", file=sys.stderr)
    from .language import REPLY_LANGUAGE, REPLY_LANGUAGE_NAME, translating
    print(f"The agent works and answers in: {REPLY_LANGUAGE}"
          + (f" (nothing is translated: the agent reads and writes {REPLY_LANGUAGE_NAME})" if not translating()
             else f" (translated into Wolof by {used['mt']})"), file=sys.stderr)
    if not translating() and REPLY_LANGUAGE != "wo" and (os.environ.get("WAXAL_STT") or "elevenlabs").lower() == "soynade":
        print("Warning: Soynade recognises Wolof only: with no translation and a language other than Wolof, use WAXAL_STT=elevenlabs.", file=sys.stderr)
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
    pipeline = build_pipeline(args.data, args.documents, refresh=s3.refresh_user if s3 else None, instructions=args.instructions, skills=args.skills)
    from . import browsing
    from .agent import skills_report
    print(skills_report(getattr(pipeline.agent, "skills", None)), file=sys.stderr)
    print(browsing.report(), file=sys.stderr)
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
