"""Wolof speech by ElevenLabs: POST /v1/text-to-speech/{voice_id}?output_format=pcm_16000 (raw 16-bit 16 kHz mono, wrapped as WAV).

    {"text": ..., "model_id": "eleven_v4", "language_code": "fr"}

eleven_v4 does not accept Wolof ("does not support language_code 'wo'") and read Wolof text with English pronunciation when no
language was given. French is the closest it has: the Wolof spelling is French-like. It is a stand-in, not a Wolof voice.
ELEVENLABS_VOICE_ID (any voice of your account; default: George, the voice of their example), ELEVENLABS_TTS_MODEL (default
eleven_v4), ELEVENLABS_TTS_LANGUAGE (default fr; empty: the field is left out and the language is guessed),
ELEVENLABS_TTS_FORMAT (default pcm_16000; an mp3_... format is converted with ffmpeg).
"""

import io
import os
import wave

from ..elevenlabs_api import ElevenLabsClient
from ..language import REPLY_LANGUAGE, TTS_CODES, translating

DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"  # "George", the voice of ElevenLabs' own example


class ElevenLabsSpeaker:
    def __init__(self, client: ElevenLabsClient | None = None) -> None:
        self.client = client or ElevenLabsClient()
        env = os.environ
        self.voice = env.get("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE
        self.model = env.get("ELEVENLABS_TTS_MODEL") or "eleven_v4"
        # no Wolof in eleven_v4: French reads Wolof spelling best. With WAXAL_TRANSLATION=off, the language that is spoken.
        self.language = env.get("ELEVENLABS_TTS_LANGUAGE", "fr" if translating() else TTS_CODES.get(REPLY_LANGUAGE, "fr"))
        self.format = env.get("ELEVENLABS_TTS_FORMAT") or "pcm_16000"
        self.stream_format = env.get("ELEVENLABS_STREAM_FORMAT") or "mp3_44100_64"  # what speak_stream sends: playable as it arrives

    def request_body(self, text: str) -> dict:
        body = {"text": text, "model_id": self.model}
        if self.language:
            body["language_code"] = self.language
        return body

    def speak_stream(self, text: str):
        """(media type, an iterator of audio bytes) of the voice of `text`, from ElevenLabs' streaming route: the first bytes come
        before the whole clip is made. Errors (a refusal, no credit) are raised here, before any byte is returned."""
        response = self.client.stream_post(f"v1/text-to-speech/{self.voice}/stream", params={"output_format": self.stream_format},
                                           json=self.request_body(text))

        def body():
            try:
                yield from response.iter_bytes()
            finally:
                response.close()
        media = "audio/mpeg" if self.stream_format.startswith("mp3_") else "application/octet-stream"
        return media, body()

    def speak(self, text: str) -> bytes:
        response = self.client.post(f"v1/text-to-speech/{self.voice}", params={"output_format": self.format},
                                    json=self.request_body(text))
        if not self.format.startswith("pcm_"):  # mp3 and the like: ffmpeg makes the WAV
            from .. import audio
            return audio.to_wav(response.content)
        out = io.BytesIO()
        with wave.open(out, "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
            w.writeframes(response.content)
        return out.getvalue()
