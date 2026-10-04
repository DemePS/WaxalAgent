"""Run every stage of the real Wolof pipeline on your PC and say how long each takes.

    uv sync --extra models
    uv run python scripts/check_models.py [soynade|wolof] [recording.wav]     # engines (default soynade); a recording is optional

It translates a few English sentences to Wolof and back, speaks the Wolof into check_*.wav (listen to them: only a
Wolof speaker can judge them), and, with a recording, shows what the recogniser hears and its English.
"""

import sys
import time
from pathlib import Path

SENTENCES = ["Hello, how are you?", "The total of the invoice is six hundred and forty two euros.",
             "Please send me the file tomorrow morning."]


def timed(label, fn):
    start = time.monotonic()
    result = fn()
    print(f"  [{time.monotonic() - start:5.1f} s] {label}")
    return result


def main() -> None:
    from waxal_agent import certs
    certs.trust_system_certificates()  # before anything is downloaded: a company proxy re-signs HTTPS
    from waxal_agent.engines import build_engines
    args = sys.argv[1:]
    name = args.pop(0) if args and args[0] in ("soynade", "wolof") else "soynade"
    print(f"Engines: {name}")
    asr, mt, tts = build_engines(name)
    print("English -> Wolof -> English (does the meaning survive?)")
    for i, sentence in enumerate(SENTENCES, 1):
        wolof = timed("en -> wo", lambda s=sentence: mt.translate(s, "en", "wo"))
        back = timed("wo -> en", lambda w=wolof: mt.translate(w, "wo", "en"))
        print(f"  {sentence!r}\n    wolof: {wolof!r}\n    back:  {back!r}")
        wav = timed("speak", lambda w=wolof: tts.speak(w))
        Path(f"check_{i}.wav").write_bytes(wav)
    if args:
        print("A recording")
        wolof = timed("listen", lambda: asr.transcribe(Path(args[0]).read_bytes()))
        print(f"  heard:  {wolof!r}\n  english: {mt.translate(wolof, 'wo', 'en')!r}")
    print("Done. Listen to check_1.wav ... check_3.wav.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # a certificate failure gets a plain explanation
        from waxal_agent import certs
        help_text = certs.explain(e)
        if help_text is None:
            raise
        sys.exit(f"{e}\n\n{help_text}")
