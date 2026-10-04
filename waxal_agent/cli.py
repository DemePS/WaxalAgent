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
    raise SystemExit(f"Unknown engines {engines!r}: only 'fake' exists so far (the Wolof models come in milestone 2).")


def main() -> None:
    parser = argparse.ArgumentParser(prog="waxal-agent", description="A Wolof voice agent.")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Start the web server with the test page.")
    serve.add_argument("--engines", default="fake", help="fake (no models) -- the Wolof models come in milestone 2.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--data", default="data/users", help="Where each person's folder and conversation are kept.")
    args = parser.parse_args()
    import uvicorn

    from .server import create_app, token_from_env
    app = create_app(build_pipeline(args.engines, args.data), token_from_env())
    if not os.environ.get("WAXAL_TOKEN") and args.host not in ("127.0.0.1", "localhost"):
        print("Warning: listening beyond this PC without WAXAL_TOKEN set: anyone who can reach it can use the agent.",
              file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port)
