"""A stand-in speaker: a short tone as a valid WAV, longer for longer text."""

import io
import math
import struct
import wave


class FakeSpeaker:
    def __init__(self, rate: int = 16000) -> None:
        self.rate = rate
        self.spoken: list[str] = []

    def speak(self, text: str) -> bytes:
        self.spoken.append(text)
        seconds = min(0.1 + 0.03 * len(text), 5.0)
        frames = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / self.rate)))
                          for i in range(int(seconds * self.rate)))
        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.rate)
            w.writeframes(frames)
        return out.getvalue()
