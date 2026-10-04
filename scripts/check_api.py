"""Try Soynade's hosted API one step at a time (needs SOYNADE_API_KEY).

    uv run python scripts/check_api.py models                      # which models your key can use
    uv run python scripts/check_api.py listen recording.wav        # Wolof speech -> Wolof text
    uv run python scripts/check_api.py translate en wo "Hello"     # text translation (en wo / wo en)
    uv run python scripts/check_api.py speak "Nanga def"           # Wolof text -> speech.wav
"""

import sys
import time
from pathlib import Path

from waxal_agent import audio, certs
from waxal_agent.soynade_api import SoynadeClient, SoynadeError


def timed(fn):
    start = time.monotonic()
    result = fn()
    print(f"[{time.monotonic() - start:.1f} s]", end=" ")
    return result


def main(argv: list[str]) -> None:
    if not argv:
        sys.exit(__doc__)
    certs.trust_system_certificates()  # a company proxy re-signs HTTPS
    client = SoynadeClient()
    command, args = argv[0], argv[1:]
    if command == "models":
        print("\n".join(client.models()))
    elif command == "listen" and args:
        from waxal_agent.stt.soynade_api import SoynadeListener
        wav = audio.to_wav(Path(args[0]).read_bytes())
        print("heard:", repr(timed(lambda: SoynadeListener(client).transcribe(wav))))
    elif command == "translate" and len(args) == 3:
        from waxal_agent.mt.soynade_api import SoynadeTranslator
        mt = SoynadeTranslator(client)
        print(f"model {mt.model}:", repr(timed(lambda: mt.translate(args[2], args[0], args[1]))))
    elif command == "speak" and args:
        from waxal_agent.tts.soynade_api import SoynadeSpeaker
        speaker = SoynadeSpeaker(client)
        wav = timed(lambda: speaker.speak(" ".join(args)))
        Path("speech.wav").write_bytes(wav)
        print(f"model {speaker.model}: {len(wav)} bytes -> speech.wav (play it)")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except (SoynadeError, audio.AudioError) as e:
        help_text = certs.explain(e)
        sys.exit(f"Failed: {e}" + (f"\n\n{help_text}" if help_text else ""))
