"""WhatsApp (Meta's WhatsApp Business Cloud API): the webhook, downloading voice notes, sending replies.

A person sends a voice note (or types Wolof) to the business number; Meta calls our webhook; we answer with a voice
note and the same words in text. Everything needed from the outside comes from environment variables:

    WHATSAPP_TOKEN              access token of the Meta app (a system user's permanent token)
    WHATSAPP_PHONE_NUMBER_ID    the id of the business phone number (not the number itself)
    WHATSAPP_VERIFY_TOKEN       any secret string you also type in Meta's webhook settings
    WHATSAPP_APP_SECRET         the app's secret: the signature of every webhook call is checked with it
    WAXAL_ALLOWED               phone numbers allowed to talk to the agent (digits, comma-separated); empty: nobody
    WHATSAPP_GRAPH_VERSION      Graph API version, default v21.0 (check Meta's current one)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass, field

import httpx

from . import audio
from .language import REPLY_LANGUAGE, translating
from .pipeline import Pipeline

log = logging.getLogger("waxal.whatsapp")

GRAPH = "https://graph.facebook.com"
SORRY = "Sorry, something went wrong. Please try again."
ONLY_VOICE_AND_TEXT = "I can only listen to voice notes and read text messages."
FILE_SAVED = "I added the file to the library: {name}."
ONLY_ADMINS_ADD_DOCUMENTS = "Only the administrators can add documents. You can ask me questions about the documents I have."
# The fixed messages in French, for WAXAL_TRANSLATION=off with French as the language (nothing is translated, so they are written here).
FRENCH = {
    SORRY: "Désolé, une erreur s'est produite. Veuillez réessayer.",
    ONLY_VOICE_AND_TEXT: "Je ne peux écouter que les messages vocaux et lire les messages texte.",
    FILE_SAVED: "J'ai ajouté le fichier à la bibliothèque : {name}.",
    ONLY_ADMINS_ADD_DOCUMENTS: "Seuls les administrateurs peuvent ajouter des documents. Vous pouvez me poser des questions sur les documents que j'ai.",
}
NOT_ALLOWED = "Sorry, this number is not allowed to use this service."


def digits(number: str) -> str:
    return "".join(c for c in number if c.isdigit())


def with_links(text: str, links: list[dict]) -> str:
    """The reply and, under it, the links the agent shared (one per line: label, then the address)."""
    return text + "".join(f"\n\n{link['label']}: {link['url']}" for link in links)


@dataclass
class WhatsAppConfig:
    token: str
    phone_number_id: str
    verify_token: str
    app_secret: str
    allowed: set[str] = field(default_factory=set)
    admins: set[str] = field(default_factory=set)  # may add documents to the library by sending them in the chat
    graph_version: str = "v21.0"

    @classmethod
    def from_env(cls, env=os.environ) -> "WhatsAppConfig":
        missing = [name for name in ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_VERIFY_TOKEN",
                                     "WHATSAPP_APP_SECRET") if not env.get(name)]
        if missing:
            raise SystemExit("WhatsApp needs these environment variables: " + ", ".join(missing))
        allowed = {digits(n) for n in env.get("WAXAL_ALLOWED", "").split(",") if digits(n)}
        admins = {digits(n) for n in env.get("WAXAL_ADMINS", "").split(",") if digits(n)}
        return cls(env["WHATSAPP_TOKEN"], env["WHATSAPP_PHONE_NUMBER_ID"], env["WHATSAPP_VERIFY_TOKEN"],
                   env["WHATSAPP_APP_SECRET"], allowed, admins, env.get("WHATSAPP_GRAPH_VERSION") or "v21.0")


class WhatsAppClient:
    """The calls we make to Meta."""

    def __init__(self, config: WhatsAppConfig, http: httpx.Client | None = None) -> None:
        self.config = config
        self.http = http or httpx.Client(timeout=30)
        self._headers = {"Authorization": f"Bearer {config.token}"}

    def _url(self, path: str) -> str:
        return f"{GRAPH}/{self.config.graph_version}/{path}"

    def download_media(self, media_id: str) -> bytes:
        info = self.http.get(self._url(media_id), headers=self._headers)
        info.raise_for_status()
        data = self.http.get(info.json()["url"], headers=self._headers)  # the download also needs the token
        data.raise_for_status()
        return data.content

    def _send(self, to: str, kind: str, body: dict) -> None:
        response = self.http.post(self._url(f"{self.config.phone_number_id}/messages"), headers=self._headers,
                                  json={"messaging_product": "whatsapp", "to": to, "type": kind, kind: body})
        response.raise_for_status()

    def send_text(self, to: str, text: str) -> None:
        self._send(to, "text", {"body": text[:4000]})

    def send_voice(self, to: str, ogg_opus: bytes) -> None:
        upload = self.http.post(self._url(f"{self.config.phone_number_id}/media"), headers=self._headers,
                                data={"messaging_product": "whatsapp", "type": "audio/ogg"},
                                files={"file": ("reply.ogg", ogg_opus, "audio/ogg")})
        upload.raise_for_status()
        self._send(to, "audio", {"id": upload.json()["id"]})


def signature_ok(body: bytes, header: str | None, app_secret: str) -> bool:
    """Meta signs every call: X-Hub-Signature-256 = sha256=<HMAC-SHA256 of the raw body with the app secret>."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header.removeprefix("sha256="), expected)


def messages_in(payload: dict) -> list[dict]:
    """The messages of a webhook call (status updates and other events are not messages)."""
    found = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue
            found += (change.get("value") or {}).get("messages", [])
    return found


class WhatsAppBot:
    def __init__(self, pipeline: Pipeline, client: WhatsAppClient, config: WhatsAppConfig) -> None:
        self.pipeline, self.client, self.config = pipeline, client, config
        self.files = None  # the Library: documents and photos sent by an administrator are added to it
        self._seen: OrderedDict[str, None] = OrderedDict()  # Meta can deliver a message twice
        self._lock = threading.Lock()

    # --- the webhook's two kinds of call
    def verify(self, params: dict) -> str | None:
        """GET: Meta checks the address once. Returns the challenge to echo, or None to refuse."""
        if params.get("hub.mode") == "subscribe" and hmac.compare_digest(
                str(params.get("hub.verify_token", "")), self.config.verify_token):
            return str(params.get("hub.challenge", ""))
        return None

    def handle(self, payload: dict) -> None:
        """POST: every message in it, one at a time. Never raises (Meta would retry the whole call)."""
        for message in messages_in(payload):
            try:
                self._handle_message(message)
            except Exception:  # one bad message must not stop the others
                log.exception("Could not handle a WhatsApp message")

    # --- one message
    def _first_time(self, message_id: str) -> bool:
        with self._lock:
            if message_id in self._seen:
                return False
            self._seen[message_id] = None
            while len(self._seen) > 2000:
                self._seen.popitem(last=False)
            return True

    def _handle_message(self, message: dict) -> None:
        sender = digits(message.get("from", ""))
        if not sender or not self._first_time(message.get("id", "")):
            return
        if sender not in self.config.allowed:
            log.warning("Refused a message from a number that is not allowed (ends with %s)", sender[-3:])
            return  # no answer: do not confirm to strangers that the number is a service
        kind = message.get("type")
        try:
            if kind == "audio":
                result = self.pipeline.from_audio(sender, self.client.download_media(message["audio"]["id"]), speak=False)
            elif kind == "text":
                result = self.pipeline.from_wolof(sender, message["text"]["body"], speak=False)
            elif kind in ("document", "image") and self.files is not None:
                if sender in self.config.admins:
                    self._keep_file(sender, kind, message)
                else:
                    self._say(sender, ONLY_ADMINS_ADD_DOCUMENTS)
                return
            else:
                self._say(sender, ONLY_VOICE_AND_TEXT)
                return
        except audio.AudioError:
            self._say(sender, SORRY)
            return
        except Exception:
            log.exception("The turn failed")
            self._say(sender, SORRY)
            return
        if result.reply_wolof:
            self.client.send_text(sender, with_links(result.reply_wolof, result.links))  # the text first: the voice may be slow, or fail
            try:
                wav, _ = self.pipeline.speak_text(result.reply_wolof)
                if wav:
                    self.client.send_voice(sender, audio.to_ogg_opus(wav))
            except Exception:
                log.exception("The voice note could not be made or sent")

    def _keep_file(self, sender: str, kind: str, message: dict) -> None:
        """A document or photo sent in the chat goes to the person's folder; the answer says so (or why not)."""
        from .files import FileRefused
        info = message[kind]
        name = info.get("filename") or f"photo-{info['id'][-8:]}" + (".png" if "png" in info.get("mime_type", "") else ".jpg")
        try:
            saved = self.files.save(name, self.client.download_media(info["id"]))
        except FileRefused as e:
            self._say(sender, str(e))
            return
        except Exception:
            log.exception("Could not keep a file")
            self._say(sender, SORRY)
            return
        self._say(sender, FILE_SAVED, name=saved)

    def _say(self, to: str, english: str, **fields) -> None:
        """A fixed message, translated like every reply (no Wolof is written by hand here). With nothing translated it is sent as it is: in
        French when that is the language, else in English."""
        if translating():
            try:
                text = self.pipeline.translator.translate(english.format(**fields) if fields else english, "en", "wo")
            except Exception:
                text = english.format(**fields) if fields else english
        else:
            text = FRENCH.get(english, english) if REPLY_LANGUAGE == "fr" else english
            text = text.format(**fields) if fields else text
        self.client.send_text(to, text)
