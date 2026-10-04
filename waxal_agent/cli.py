"""waxal-agent serve: start the test page (and later the WhatsApp webhook)."""

import argparse
import os
import sys


def build_pipeline(engines: str, data: str):
    from .agent import AgentTurns
    from .engines import build_engines
    from .pipeline import Pipeline
    listener, translator, speaker = build_engines(engines)
    return Pipeline(listener, translator, speaker, AgentTurns(data))


def main() -> None:
    parser = argparse.ArgumentParser(prog="waxal-agent", description="A Wolof voice agent.")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Start the web server with the test page.")
    serve.add_argument("--engines", default=None, help="soynade (recognition, translation and Wolof voice, all through Soynade's API; the default when SOYNADE_API_KEY is set), soynade-asr (only recognition is real) or fake (stand-ins, the default without a key).")
    serve.add_argument("--whatsapp", action="store_true",
                       help="Answer WhatsApp voice notes at /webhook (needs the WHATSAPP_* variables, see README).")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--data", default="data/users", help="Where each person's folder and conversation are kept.")
    args = parser.parse_args()
    import logging

    import uvicorn

    logging.basicConfig(level=os.environ.get("WAXAL_LOG", "INFO").upper(), format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per HTTP request adds nothing here
    from . import certs
    certs.trust_system_certificates()  # a company proxy re-signs HTTPS (models, Meta)
    from .server import create_app, token_from_env
    engines = args.engines or ("soynade" if os.environ.get("SOYNADE_API_KEY") else "fake")
    print(f"Engines: {engines}" + (" (stand-ins: no Wolof is really heard, translated or spoken; set SOYNADE_API_KEY)" if engines == "fake" else ""),
          file=sys.stderr)
    from .language import REPLY_LANGUAGE
    print(f"The agent works and answers in: {REPLY_LANGUAGE}" + ("" if REPLY_LANGUAGE == "wo" else " (translated into Wolof by Soynade)"),
          file=sys.stderr)
    pipeline = build_pipeline(engines, args.data)
    bot = None
    if args.whatsapp:
        from .whatsapp import WhatsAppBot, WhatsAppClient, WhatsAppConfig
        config = WhatsAppConfig.from_env()
        bot = WhatsAppBot(pipeline, WhatsAppClient(config), config)
        if not config.allowed:
            print("Warning: WAXAL_ALLOWED is empty: nobody can use the agent yet.", file=sys.stderr)
    # With WhatsApp on a public server, the test page is only offered when a token protects it.
    from .files import UserFiles
    user_files = UserFiles(args.data)
    if bot is not None:
        bot.files = user_files
    app = create_app(pipeline, token_from_env(), bot, test_page=(bot is None or token_from_env() is not None), files=user_files)
    if not os.environ.get("WAXAL_TOKEN") and args.host not in ("127.0.0.1", "localhost"):
        print("Warning: listening beyond this PC without WAXAL_TOKEN set: anyone who can reach it can use the agent.",
              file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port)
