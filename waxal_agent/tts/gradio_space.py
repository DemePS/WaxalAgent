"""Oolel-Voices through Soynade's public demo (a Hugging Face Space), called like an API. Nothing runs on your machine.

Soynade's own API does not offer speech output yet (WAXAL_TTS=soynade), but its Oolel-Voices demo is a Gradio Space
(`soynade-research/Oolel-Voices-Demo`), and a Gradio Space can be called from code (needs `uv sync --extra demo`).

This is a stop-gap, not a service: the demo is shared, may queue or sleep, can change its inputs or disappear without
notice, and may have usage limits or terms of its own (read them; and the Oolel-Voices model card for its licence). The
endpoint is found automatically: the first one that takes a text and returns audio; the other inputs get their defaults.
If the demo needs a reference voice, give a short WAV in WAXAL_TTS_VOICE; extra inputs as JSON in WAXAL_TTS_SPACE_ARGS
({"parameter_name": value}). `scripts/check_api.py speak "..."` with WAXAL_TTS=oolel-demo shows what was found.

    WAXAL_TTS_SPACE   the Space (default soynade-research/Oolel-Voices-Demo)
    HF_TOKEN          optional: an access token raises the limits of the Space
"""

import json
import os
from pathlib import Path

from .. import audio
from .base import SpeechUnavailable

DEFAULT_SPACE = "soynade-research/Oolel-Voices-Demo"


class GradioSpeaker:
    def __init__(self, space: str | None = None, client=None, voice: str | None = None) -> None:
        self.model = space or os.environ.get("WAXAL_TTS_SPACE") or DEFAULT_SPACE
        self.voice = voice or os.environ.get("WAXAL_TTS_VOICE") or None
        self._client = client  # tests give a fake; None: gradio_client
        self._endpoint = None

    def _connect(self):
        if self._client is None:
            try:
                from gradio_client import Client
            except ImportError:
                raise SpeechUnavailable("The demo voice needs the gradio client: uv sync --extra demo")
            from .. import certs
            certs.trust_system_certificates()
            try:
                token = os.environ.get("HF_TOKEN") or None
                self._client = Client(self.model, hf_token=token) if token else Client(self.model, verbose=False)
            except Exception as e:  # sleeping, private, renamed, or no network
                raise SpeechUnavailable(f"Could not open the Space {self.model}: {type(e).__name__}: {str(e)[:200]}")
        return self._client

    def _find_endpoint(self, client):
        """(api_name, parameters): the first named endpoint that takes a text and returns audio."""
        info = client.view_api(return_format="dict", print_info=False)
        for name, endpoint in (info.get("named_endpoints") or {}).items():
            returns = [str(r.get("component", "")).lower() for r in endpoint.get("returns", [])]
            params = endpoint.get("parameters", [])
            if any(r in ("audio", "file") for r in returns) and any(_is_text(p) for p in params):
                return name, params
        raise SpeechUnavailable(f"The Space {self.model} has no endpoint that takes a text and returns audio "
                                f"(its endpoints: {', '.join((info.get('named_endpoints') or {}).keys()) or 'none'}).")

    def speak(self, text: str) -> bytes:
        client = self._connect()
        if self._endpoint is None:
            self._endpoint = self._find_endpoint(client)
        name, params = self._endpoint
        extra = json.loads(os.environ.get("WAXAL_TTS_SPACE_ARGS") or "{}")
        kwargs, text_done = {}, False
        for p in params:
            key = p.get("parameter_name") or p.get("label")
            if key in extra:
                kwargs[key] = extra[key]
            elif _is_text(p) and not text_done:
                kwargs[key], text_done = text, True
            elif _is_media(p) and self.voice:
                from gradio_client import handle_file
                kwargs[key] = handle_file(self.voice)
            elif p.get("parameter_has_default"):
                kwargs[key] = p.get("parameter_default")
            else:
                raise SpeechUnavailable(f"The Space {self.model} needs an input I cannot fill: {key!r} "
                                        f"({p.get('component')}). Give it in WAXAL_TTS_SPACE_ARGS, or a voice in WAXAL_TTS_VOICE.")
        try:
            result = client.predict(api_name=name, **kwargs)
        except Exception as e:
            raise SpeechUnavailable(f"The Space {self.model} failed: {type(e).__name__}: {str(e)[:300]}")
        path = _first_path(result)
        if path is None:
            raise SpeechUnavailable(f"The Space {self.model} returned no audio file: {str(result)[:200]}")
        return audio.to_wav(Path(path).read_bytes())


def _is_text(p: dict) -> bool:
    return str(p.get("component", "")).lower() in ("textbox", "text") or (p.get("python_type") or {}).get("type") == "str" \
        and str(p.get("component", "")).lower() not in ("audio", "file", "dropdown", "radio")


def _is_media(p: dict) -> bool:
    return str(p.get("component", "")).lower() in ("audio", "file")


def _first_path(result):
    """The audio file path in what a Space returns (a path, or a tuple / list / dict holding one)."""
    if isinstance(result, str) and Path(result).is_file():
        return result
    if isinstance(result, dict):
        return _first_path(result.get("path") or result.get("value") or list(result.values()))
    if isinstance(result, (list, tuple)):
        for item in result:
            found = _first_path(item)
            if found:
                return found
    return None
