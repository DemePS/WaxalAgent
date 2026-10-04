"""Turning the agent's written reply into something that can be translated and spoken."""

import re

_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+")
_MARKUP = re.compile(r"[*_`#>]+")
_BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.MULTILINE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def speakable(text: str) -> str:
    """Plain sentences only: no code blocks, tables, links or markdown (they stay in the written reply)."""
    text = _CODE_BLOCK.sub(" ", text)
    text = _TABLE_LINE.sub(" ", text)
    text = _LINK.sub(r"\1", text)
    text = _URL.sub(" ", text)
    text = _BULLET.sub("", text)
    text = _MARKUP.sub("", text)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n{2,}", "\n", text)).strip()


def sentences(text: str, limit: int = 200) -> list[str]:
    """Split into pieces short enough for a translation or speech model (a long sentence is cut at a space)."""
    out: list[str] = []
    for line in text.splitlines():
        for part in _SENTENCE_END.split(line.strip()):
            part = part.strip()
            while len(part) > limit:
                cut = part.rfind(" ", 0, limit)
                cut = cut if cut > 0 else limit
                out.append(part[:cut].strip())
                part = part[cut:].strip()
            if part:
                out.append(part)
    return out


def chunks(text: str, limit: int = 600) -> list[str]:
    """The text in as few pieces as possible, each at most `limit` characters, cut between sentences: one API call per
    piece (an API with a rate limit is called once per piece, not once per sentence)."""
    pieces: list[str] = []
    current = ""
    for sentence in sentences(text, limit):
        if current and len(current) + 1 + len(sentence) > limit:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces
