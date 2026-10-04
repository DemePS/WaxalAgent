"""waxal-agent serve: start the test page (and later the WhatsApp webhook)."""

import argparse
import os
import sys


def build_pipeline(engines: str, data: str):
    from .agent import AgentTurns
    from .pipeline import Pipeline
    if engines == "fake":
        from .mt.fake import FakeTranslator
        from .stt.fake import FakeListener
        from .tts.fake import FakeSpeaker
        return Pipeline(FakeListener(default="Nanga def?"), FakeTranslator(), FakeSpeaker(), AgentTurns(data))
    if engines == "wolof":
        from .mt.nllb import Nllb
        from .stt.whisper_wolof import WhisperWolof
        from .tts.speecht5_wolof import SpeechT5Wolof
        return Pipeline(WhisperWolof(), Nllb(), SpeechT5Wolof(), AgentTurns(data))
    raise SystemExit(f"Unknown engines {engines!r}: use 'fake' (no models) or 'wolof' (the real models, `uv sync --extra models`).")


def main() -> None:
    parser = argparse.ArgumentParser(prog="waxal-agent", description="A Wolof voice agent.")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Start the web server with the test page.")
    serve.add_argument("--engines", default="fake", help="fake (no models) or wolof (the real models: uv sync --extra models).")
    serve.add_argument("--whatsapp", action="store_true",
                       help="Answer WhatsApp voice notes at /webhook (needs the WHATSAPP_* variables, see README).")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--data", default="data/users", help="Where each person's folder and conversation are kept.")
    args = parser.parse_args()
    import uvicorn

    from .server import create_app, token_from_env
    pipeline = build_pipeline(args.engines, args.data)
    bot = None
    if args.whatsapp:
        from .whatsapp import WhatsAppBot, WhatsAppClient, WhatsAppConfig
        config = WhatsAppConfig.from_env()
        bot = WhatsAppBot(pipeline, WhatsAppClient(config), config)
        if not config.allowed:
            print("Warning: WAXAL_ALLOWED is empty: nobody can use the agent yet.", file=sys.stderr)
    # With WhatsApp on a public server, the test page is only offered when a token protects it.
    app = create_app(pipeline, token_from_env(), bot, test_page=(bot is None or token_from_env() is not None))
    if not os.environ.get("WAXAL_TOKEN") and args.host not in ("127.0.0.1", "localhost"):
        print("Warning: listening beyond this PC without WAXAL_TOKEN set: anyone who can reach it can use the agent.",
              file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port)
