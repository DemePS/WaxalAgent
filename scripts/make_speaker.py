"""Write a PLACEHOLDER speaker embedding for SpeechT5 (data/speaker.npy: 512 numbers) so the sandbox can start.

The voice it gives is arbitrary and may sound odd: replace it with a real x-vector of a voice you like (the SpeechT5
tutorials extract one from a recording with speechbrain) once the pipeline works.

    uv run --with numpy python scripts/make_speaker.py        # writes data/speaker.npy (the sandbox's data folder)
"""

import numpy

rng = numpy.random.default_rng(0)
vector = rng.normal(size=512).astype("float32")
vector /= numpy.linalg.norm(vector)
import pathlib
pathlib.Path("data").mkdir(exist_ok=True)
numpy.save("data/speaker.npy", vector)
print("Wrote data/speaker.npy (a placeholder voice).")
