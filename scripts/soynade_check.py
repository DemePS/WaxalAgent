#!/usr/bin/env python3
"""Calls to api.soynade.ai with the key in .env.

Uses the eval script's own load_key(), so it proves exactly what the eval will
load. The key is never printed, only its origin and a masked fingerprint.
Nothing is written to disk.

    uv run python scripts/soynade_check.py           # is the key accepted?
    uv run python scripts/soynade_check.py speak     # how long does the voice take?

Default: translates two Wolof words ($1.50 / 1M input tokens, a fraction of a
cent).  `speak`: two text-to-speech calls, a short text and a long one, each
timed in two parts -- until the answer starts (Soynade making the audio) and
then until the last byte (the download).  About 345 characters at $0.22 / 1K,
roughly $0.08.
"""

from __future__ import annotations

import json
import pathlib
import struct
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from soynade_eval import API, UA, load_key  # noqa: E402

SHORT = "Naka nga def? Jàmm rekk."
LONG = ("Naka nga def? Jàmm rekk, ñun ngi fi. Tey jii, bëccëg bi dafa tàng lool, waaye "
        "ngelaw li dafa neex. Soo bëggee dem marse bi, war nga génn ci suba teel, ndaxte "
        "bi ñu ko ubbee, nit ñi dañuy bare lool. Jërëjëf, ba beneen yoon.")


def wav_info(data: bytes) -> str:
    """Sample rate, channels and duration of a WAV, read from its header."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return "not a WAV"
    riff = struct.unpack("<I", data[4:8])[0]
    rate = channels = bits = 0
    frames = 0
    pos = 12
    while pos + 8 <= len(data):
        name, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if name == b"fmt ":
            channels, rate = struct.unpack("<HI", data[pos + 10:pos + 16])
            bits = struct.unpack("<H", data[pos + 22:pos + 24])[0]
        elif name == b"data":
            frames = min(size, len(data) - pos - 8)
            break
        pos += 8 + size + (size & 1)
    seconds = frames / (rate * channels * bits / 8) if rate and channels and bits else 0.0
    header = "" if riff == len(data) - 8 else f", RIFF size field {riff} (file is {len(data) - 8})"
    return f"{rate} Hz, {channels} ch, {bits}-bit, {seconds:.2f} s of audio{header}"


def speak(key: str, text: str) -> None:
    """One /v1/text-to-speech call, timed in two parts: making the audio, then downloading it."""
    print(f"\n{len(text)} characters: {text[:60]}{'…' if len(text) > 60 else ''}")
    req = urllib.request.Request(
        API + "/v1/text-to-speech",
        data=json.dumps({"text": text, "language": "wo", "output_format": "wav"}).encode(),
        method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}", **UA},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            answered = time.monotonic()          # headers are in: Soynade has finished making the audio
            status, headers, body = r.status, r.headers, r.read()
            done = time.monotonic()
    except urllib.error.HTTPError as e:
        answered = time.monotonic()
        status, headers, body = e.code, e.headers, e.read()
        done = time.monotonic()
    except Exception as e:
        print(f"   network error after {time.monotonic() - started:.2f}s: {e!r}")
        return
    if status != 200:
        print(f"   HTTP {status} after {done - started:.2f}s: {' '.join(body.decode('utf-8', 'replace').split())[:200]}")
        for name, value in headers.items():   # retry-after / x-ratelimit-*: how long the server wants us to wait
            if "ratelimit" in name.lower() or name.lower() in ("retry-after", "x-request-id"):
                print(f"      {name}: {value}")
        return
    print(f"   making the audio   {answered - started:6.2f}s   (request sent -> answer starts)")
    print(f"   downloading it     {done - answered:6.2f}s   ({len(body)} bytes, {headers.get('content-type', '')})")
    print(f"   total              {done - started:6.2f}s")
    print(f"   {wav_info(body)}")


def main() -> int:
    key, origin = load_key()
    print(f"key loaded from {origin}: {key[:5]}…{key[-2:]} ({len(key)} chars)")

    if len(sys.argv) > 1 and sys.argv[1] == "speak":
        for text in (SHORT, LONG):
            speak(key, text)
        print("\nCompare 'making the audio' with the gap you see in the page: what is left over "
              "is this code (throttle, ffmpeg, base64) and the browser, not Soynade.")
        return 0

    req = urllib.request.Request(
        API + "/v1/translations",
        data=json.dumps({"text": "nanga def",
                         "source_language": "wo",
                         "target_language": "fr"}).encode(),
        method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}", **UA},
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            status, body = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read()
    except Exception as e:
        print(f"network error: {e!r}")
        return 2

    text = body.decode("utf-8", "replace")
    if status == 200:
        print("200 OK — the key is accepted")
        print("   wo 'nanga def' ->", json.loads(text).get("translated_text"))
        print("\nThe eval can be run:  uv run python scripts/soynade_eval.py -n 20")
        return 0

    print(f"{status} — the key was rejected")
    print(" ".join(text.split())[:300])
    if status in (401, 403):
        print("\nCompare the key in .env with console.soynade.ai and replace the "
              "line there. Do not paste it in chat.")
    elif status in (402, 429):
        print("\nThis is not an auth problem: credits or rate limit.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
