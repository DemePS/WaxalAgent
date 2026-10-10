#!/usr/bin/env python3
"""Create a new WaxalAgent app from the template, next to the library.

    python cookie-cutter/new_app.py aidchat --title "AidChat" --purpose "Help people with questions about aid applications." \\
        --language fr --domains "service-public.fr=Service Public" --brand "#0b6e8a"

It writes ../<slug>/ with the command, the page, the instructions, one base skill, the Dockerfile, the settings and the tests.
Only the standard library is used: no cookiecutter package to install.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template"
LANGUAGES = ("fr", "en", "wo")
SLUG = re.compile(r"^[a-z][a-z0-9]{1,30}$")
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def values(args: argparse.Namespace) -> dict[str, str]:
    """Everything a template file may use, as {{name}}."""
    title = args.title or args.slug.capitalize()
    domains = [d.strip() for d in (args.domains or "").split(",") if d.strip()]
    if domains:
        link_line = "WAXAL_LINK_DOMAINS=" + ", ".join(domains)
        sites = ", ".join(d.split("=")[-1] if "=" in d else d for d in domains)
        sites_section = (
            "2. **The allowed websites**: " + sites + ". Use them to explain, and for what the library does not give. Go straight to the right\\n"
            "   page; one page is enough when it answers.\\n\\n"
            "Answer from what you read, naming each source; if the sources differ, say so. If they do not answer, say so and suggest who to ask.\\n"
        ).replace("\\n", "\n")
        and_sites = " and the allowed websites"
    else:
        link_line = "# WAXAL_LINK_DOMAINS=example.org=Example     (not set: no browsing, no link)"
        sites_section = "\nAnswer from what you read, naming the document. If it does not answer, say so and suggest who to ask.\n"
        and_sites = ""
    if args.language == "wo":
        language_settings = "# Wolof in and out, translated (the default): nothing to set."
    else:
        language_settings = (f"# {args.language}: no translation, the agent reads and answers in {args.language} and the answer is spoken as it is.\n"
                             f"WAXAL_TRANSLATION=off\nWAXAL_REPLY_LANGUAGE={args.language}")
    return {
        "app_slug": args.slug, "app_title": title, "description": args.description or f"{title}, built on the WaxalAgent library.",
        "purpose": args.purpose or f"You answer the questions of the people who use {title}, from its library.",
        "language": args.language, "brand_color": args.brand, "link_domains_line": link_line, "language_settings": language_settings,
        "sites_section": sites_section, "and_sites": and_sites,
    }


def render(text: str, values_: dict[str, str]) -> str:
    for key, value in values_.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def create(out: Path, values_: dict[str, str]) -> list[Path]:
    """Copy the template into `out` (which must not exist), names and contents rendered. Returns the files written."""
    if out.exists():
        raise SystemExit(f"{out} already exists: choose another name or remove it.")
    written = []
    for source in sorted(TEMPLATE.rglob("*")):
        if not source.is_file():
            continue
        target = out / Path(render(str(source.relative_to(TEMPLATE)), values_))
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = source.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            target.write_bytes(source.read_bytes())
        else:
            rendered = render(text, values_)
            left = re.findall(r"\{\{[a-z_]+\}\}", rendered)
            if left:
                raise SystemExit(f"{source.relative_to(TEMPLATE)}: unknown placeholder {left[0]}")
            target.write_text(rendered, encoding="utf-8")
        written.append(target)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a new WaxalAgent app from the template.")
    parser.add_argument("slug", help="the package and command name: lower case letters and digits, e.g. aidchat")
    parser.add_argument("--title", help="the name shown to people (default: the slug, capitalised)")
    parser.add_argument("--description", help="one sentence for pyproject.toml and the README")
    parser.add_argument("--purpose", help="what the agent is for: one or two sentences, written in the instructions")
    parser.add_argument("--language", choices=LANGUAGES, default="fr", help="the language people speak and the agent answers in (default fr)")
    parser.add_argument("--brand", default="#0a7d5a", help="the accent colour of the page, #rrggbb")
    parser.add_argument("--domains", help="the trusted websites: 'domain=Name, domain=Name' (empty: no browsing, no link)")
    parser.add_argument("--out", help="where to create the app (default: next to the library, ../<slug>)")
    parser.add_argument("--git", action="store_true", help="run git init in the new folder")
    args = parser.parse_args(argv)
    if not SLUG.match(args.slug):
        parser.error("slug: lower case letters and digits only, 2 to 31 characters, starting with a letter")
    if not COLOR.match(args.brand):
        parser.error("--brand: a colour like #0a7d5a")
    out = Path(args.out).expanduser().resolve() if args.out else HERE.parent.parent / args.slug
    written = create(out, values(args))
    if args.git:
        subprocess.run(["git", "init", "-q"], cwd=out, check=False)
    print(f"Created {out} ({len(written)} files). Next:")
    print(f"  cd {out}\\n  uv sync\\n  cp example.env .env   # fill in the keys\\n  uv run {args.slug} serve".replace("\\n", "\n"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
