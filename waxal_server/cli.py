"""waxal-agent serve: start the test page (and the WhatsApp webhook) on top of the core."""

import argparse
import sys
from pathlib import Path

from waxal_agent.env import load_env
from waxal_agent.factory import build_runtime
from waxal_agent.logs import setup_logging
from waxal_agent.settings import Settings


def main(prog: str = "waxal-agent", static_dir: str | Path | None = None, title: str = "WaxalAgent") -> None:
    """The command line of the server. An app built on the library calls it with its own name, page folder (static_dir)
    and title: `main("senassurchat", Path(__file__).parent / "static", "SenAssurChat")`."""
    load_env()
    settings = Settings.from_env()
    parser = argparse.ArgumentParser(prog=prog, description="A Wolof voice agent.")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Start the web server with the test page.")
    serve.add_argument("--whatsapp", action="store_true",
                       help="Answer WhatsApp voice notes at /webhook (needs the WHATSAPP_* variables, see README).")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--documents", default=settings.documents,
                       help="The library: the documents shared by every person (an administrator adds them). WAXAL_DOCUMENTS.")
    serve.add_argument("--instructions", default=settings.instructions,
                       help="The folder with INSTRUCTIONS.md: general instructions for the agent, apart from the documents. WAXAL_INSTRUCTIONS_DIR.")
    serve.add_argument("--skills", default=settings.skills,
                       help="The folder of the agent's skills (one folder with a SKILL.md each), the same for every person. WAXAL_SKILLS_DIR.")
    serve.add_argument("--data", default=settings.data, help="Where each person's folder and conversation are kept.")
    args = parser.parse_args()
    settings = settings.with_(documents=args.documents, instructions=args.instructions, skills=args.skills, data=args.data)

    import uvicorn

    from .app import create_app
    setup_logging(settings.log_level)
    runtime = build_runtime(settings, whatsapp=args.whatsapp)
    # With WhatsApp on a public server, the test page is only offered when a token protects it.
    app = create_app(runtime.pipeline, settings.token, runtime.bot,
                     test_page=(runtime.bot is None or settings.token is not None), files=runtime.files,
                     static_dir=static_dir, title=title)
    if not settings.token and args.host not in ("127.0.0.1", "localhost"):
        print("Warning: listening beyond this PC without WAXAL_TOKEN set: anyone who can reach it can use the agent.",
              file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port)
