"""Audio conversion with ffmpeg: what a browser or WhatsApp sends -> 16 kHz mono WAV, and WAV -> OGG/Opus (a WhatsApp voice note)."""

import shutil
import subprocess


class AudioError(Exception):
    """The audio could not be converted (ffmpeg missing, or the data is not audio)."""


def _ffmpeg(args: list[str], data: bytes) -> bytes:
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise AudioError("ffmpeg is not installed: install it (https://ffmpeg.org) and make sure it is on the PATH.")
    try:
        done = subprocess.run([exe, "-hide_banner", "-loglevel", "error", "-i", "pipe:0", *args, "pipe:1"],
                              input=data, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        raise AudioError("The audio took too long to convert.")
    if done.returncode != 0 or not done.stdout:
        raise AudioError("That is not audio ffmpeg can read: " + done.stderr.decode(errors="replace").strip()[:200])
    return done.stdout


def to_wav(data: bytes) -> bytes:
    """Any audio (webm/opus from a browser, ogg/opus from WhatsApp, mp3, wav...) as 16 kHz mono 16-bit WAV."""
    return _ffmpeg(["-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-f", "wav"], data)


def to_ogg_opus(wav: bytes) -> bytes:
    """WAV as OGG with the Opus codec, the format WhatsApp shows as a voice note."""
    return _ffmpeg(["-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "24k", "-f", "ogg"], wav)
