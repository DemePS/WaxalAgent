"""Wolof speech through Hugging Face's hosted inference (a web API: nothing runs on your machine).

The model is Meta's MMS text-to-speech for Wolof, `facebook/mms-tts-wol` (WAXAL_TTS_MODEL changes it). Calls go to
Hugging Face's inference router with your access token (HF_TOKEN, from huggingface.co/settings/tokens):

    POST https://router.huggingface.co/hf-inference/models/<model>    {"inputs": "<text>"}   ->  audio bytes

I could not run this where it was written (Hugging Face is not reachable there), and Hugging Face's own examples differ on
the payload key ("inputs" or "text_inputs"): `scripts/check_api.py speak "..."` with WAXAL_TTS=huggingface shows what works.
The model may not be deployed on the free serverless tier (the error then says so), and **the MMS models' licence is
CC-BY-NC 4.0: non-commercial.** Read it before using this for a paid or public service.
"""

import os
import time

import httpx

from .. import audio
from .base import SpeechUnavailable

DEFAULT_MODEL = "facebook/mms-tts-wol"
BASE_URL = "https://router.huggingface.co/hf-inference/models"
LOADING_WAIT_MAX = 30  # seconds: a cold model answers 503 "loading" for a while


class HuggingFaceSpeaker:
    def __init__(self, token: str | None = None, model: str | None = None, http: httpx.Client | None = None,
                 sleep=time.sleep) -> None:
        self.token = token or os.environ.get("HF_TOKEN") or ""
        self.model = model or os.environ.get("WAXAL_TTS_MODEL") or DEFAULT_MODEL
        self.http = http or httpx.Client(timeout=httpx.Timeout(120, connect=15))
        self.key = os.environ.get("WAXAL_TTS_KEY") or "inputs"   # the payload key, in case Hugging Face expects another
        self._sleep = sleep

    def speak(self, text: str) -> bytes:
        if not self.token:
            raise SpeechUnavailable("HF_TOKEN is not set (create an access token at huggingface.co/settings/tokens).")
        url = f"{BASE_URL}/{self.model}"
        for attempt in range(3):
            try:
                response = self.http.post(url, json={self.key: text}, headers={"Authorization": f"Bearer {self.token}"})
            except httpx.TransportError as e:
                raise SpeechUnavailable(f"Could not reach Hugging Face: {type(e).__name__}: {e}")
            if response.status_code == 200 and response.content:
                return audio.to_wav(response.content)
            detail = _detail(response)
            if response.status_code == 503 and attempt < 2:  # the model is loading: wait as long as it says
                self._sleep(min(_estimated(response), LOADING_WAIT_MAX))
                continue
            if response.status_code == 429:
                raise SpeechUnavailable(f"Hugging Face rate limit reached: {detail}")
            if response.status_code in (401, 403):
                raise SpeechUnavailable(f"Hugging Face refused the token (HTTP {response.status_code}): {detail}")
            if response.status_code in (400, 404, 422):
                raise SpeechUnavailable(f"Hugging Face cannot run {self.model} as text to speech (HTTP "
                                        f"{response.status_code}): {detail}. It may not be deployed on the serverless tier.")
            raise SpeechUnavailable(f"Hugging Face failed (HTTP {response.status_code}): {detail}")
        raise SpeechUnavailable(f"{self.model} is still loading on Hugging Face: try again in a minute.")


def _estimated(response: httpx.Response) -> float:
    try:
        return float(response.json().get("estimated_time", 10))
    except (ValueError, AttributeError):
        return 10.0


def _detail(response: httpx.Response) -> str:
    try:
        data = response.json()
        return str(data.get("error", data) if isinstance(data, dict) else data)[:300]
    except ValueError:
        return response.text[:300]
