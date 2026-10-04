"""Try Soynade's hosted API one step at a time (needs SOYNADE_API_KEY).

    uv run python scripts/check_api.py listen recording.wav        # Wolof speech -> Wolof text
    uv run python scripts/check_api.py understand recording.wav    # Wolof speech -> English text (one call)
    uv run python scripts/check_api.py translate en wo "Hello"     # text translation (en wo / wo en)
    uv run python scripts/check_api.py speak "Nanga def"           # Wolof text -> speech.wav (WAXAL_TTS=huggingface: HF_TOKEN)
    uv run python scripts/check_api.py eleven-speak "Nanga def"    # ElevenLabs: Wolof text -> speech.wav (needs ELEVENLABS_API_KEY)
    uv run python scripts/check_api.py eleven-listen recording.wav # ElevenLabs: Wolof speech -> Wolof text
    uv run python scripts/check_api.py speech-test                  # why does speech fail? short/accented/long texts, one call each
"""

import sys
import time
from pathlib import Path

from waxal_agent import audio, certs
from waxal_agent.soynade_api import SoynadeClient, SoynadeError
from waxal_agent.tts.base import SpeechUnavailable


def timed(fn):
    start = time.monotonic()
    result = fn()
    print(f"[{time.monotonic() - start:.1f} s]", end=" ")
    return result


SPEECH_TESTS = (
    ("short, plain ASCII", "Nanga def? Mangi fi rekk."),
    ("short, accented", "Ñetti téere yi nga am. Dara soppiku-ul."),
    ("long (about 300 characters), accented",
     "Maalaykum salaam, maa ngi ci jàmm. Ñetti téere yi nga am. Bu njëkk, kodd bu asiraas bu CIMA, bu atum ñaari junni fukk ak "
     "juróom ñeent. Ñaareel bi, ab kayit bu gàtt bu leeral yenn artikal yi. Ñetteel bi, nataal bu ndaw bu tudd TODO. Dara soppiku-ul."),
    ("long, plain ASCII", "Maalaykum salaam, maa ngi ci jamm. " * 9),
)


def speech_test() -> None:
    """One text-to-speech call per text, no retries: the status and the time of each, to see what the server refuses."""
    from waxal_agent.tts.soynade_api import SoynadeSpeaker
    client = SoynadeClient(retries=0)
    speaker = SoynadeSpeaker(client)
    for label, text in SPEECH_TESTS:
        start = time.monotonic()
        try:
            response = client.post_json("text-to-speech", speaker.request_body(text))
            outcome = f"HTTP {response.status_code}, {len(response.content)} bytes"
        except SoynadeError as e:
            outcome = f"FAILED: {str(e)[:160]}"
        print(f"{label} ({len(text)} chars): {outcome} [{time.monotonic() - start:.1f} s]")


def main(argv: list[str]) -> None:
    if not argv:
        sys.exit(__doc__)
    certs.trust_system_certificates()  # a company proxy re-signs HTTPS
    command, args = argv[0], argv[1:]
    client = None if command.startswith("eleven-") else SoynadeClient()  # the ElevenLabs commands need only ELEVENLABS_API_KEY
    if command == "listen" and args:
        from waxal_agent.stt.soynade_api import SoynadeListener
        wav = audio.to_wav(Path(args[0]).read_bytes())
        print("heard:", repr(timed(lambda: SoynadeListener(client).transcribe(wav))))
    elif command == "understand" and args:
        from waxal_agent.stt.soynade_api import SoynadeListener
        wav = audio.to_wav(Path(args[0]).read_bytes())
        print("english:", repr(timed(lambda: SoynadeListener(client).translate_audio(wav))))
    elif command == "translate" and len(args) == 3:
        from waxal_agent.mt.soynade_api import SoynadeTranslator
        mt = SoynadeTranslator(client)
        print("translation:", repr(timed(lambda: mt.translate(args[2], args[0], args[1]))))
    elif command == "speech-test":
        speech_test()
    elif command == "eleven-speak" and args:
        from waxal_agent.tts.elevenlabs_api import ElevenLabsSpeaker
        speaker = ElevenLabsSpeaker()
        wav = timed(lambda: speaker.speak(" ".join(args)))
        Path("speech.wav").write_bytes(wav)
        print(f"ElevenLabs {speaker.model}, voice {speaker.voice}: {len(wav)} bytes -> speech.wav (play it)")
    elif command == "eleven-listen" and args:
        from waxal_agent.stt.elevenlabs_api import ElevenLabsListener
        wav = audio.to_wav(Path(args[0]).read_bytes())
        print("heard:", repr(timed(lambda: ElevenLabsListener().transcribe(wav))))
    elif command == "speak" and args:
        from waxal_agent.engines import build_speaker
        speaker = build_speaker(client)                      # WAXAL_TTS=soynade (default) or huggingface
        wav = timed(lambda: speaker.speak(" ".join(args)))
        Path("speech.wav").write_bytes(wav)
        print(f"{type(speaker).__name__} {speaker.model}: {len(wav)} bytes -> speech.wav (play it)")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except SpeechUnavailable as e:
        sys.exit(f"No voice: {e}")
    except (SoynadeError, audio.AudioError) as e:
        help_text = certs.explain(e)
        sys.exit(f"Failed: {e}" + (f"\n\n{help_text}" if help_text else ""))
