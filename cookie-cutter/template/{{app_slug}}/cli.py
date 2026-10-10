"""The `{{app_slug}}` command: the library's server with this app's page."""

from pathlib import Path

from waxal_server.cli import main as serve

STATIC = Path(__file__).parent / "static"


def main() -> None:
    serve(prog="{{app_slug}}", static_dir=STATIC, title="{{app_title}}")
