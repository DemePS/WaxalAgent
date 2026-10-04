"""Try Soynade's hosted speech recognition on a Wolof recording (a WAV file).

    export SOYNADE_API_KEY=...
    uv run python scripts/check_api.py my_recording.wav
"""

import sys
import time
from pathlib import Path

from waxal_agent import audio, certs
from waxal_agent.soynade_api import SoynadeError
from waxal_agent.stt.soynade_api import SoynadeListener

if len(sys.argv) < 2:
    sys.exit(__doc__)
certs.trust_system_certificates()  # a company proxy re-signs HTTPS
try:
    wav = audio.to_wav(Path(sys.argv[1]).read_bytes())  # any audio format -> 16 kHz mono WAV
    start = time.monotonic()
    text = SoynadeListener().transcribe(wav)
except (SoynadeError, audio.AudioError) as e:
    sys.exit(f"Failed: {e}")
print(f"[{time.monotonic() - start:.1f} s] heard: {text!r}")
