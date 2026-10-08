"""The settings of a run, in one place.

Settings.from_env() is the only place where the application's own choices are read from the environment (the .env file is loaded into it
by whoever starts the program: the command line, a test, another application). Everything else receives a Settings, or one of its parts:
the library never reads a setting when a module is imported, and two Settings can live in the same process.

What is NOT here: the API keys and the tuning of one vendor (ELEVENLABS_*, SOYNADE_*, WHATSAPP_*, ANTHROPIC_*). Each client reads its own
when it is built (and takes them as arguments too).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .language import Language

_OFF = ("off", "0", "no", "false")
_ON = ("1", "true", "yes", "on")
MB = 1024 * 1024


@dataclass(frozen=True)
class Settings:
    language: Language = field(default_factory=Language)
    # The engines (hosted APIs), by name.
    stt: str = "elevenlabs"     # WAXAL_STT: elevenlabs or soynade
    mt: str = "claude"          # WAXAL_MT: claude or soynade
    tts: str = "elevenlabs"     # WAXAL_TTS: elevenlabs, soynade, huggingface or oolel-demo
    # The turn.
    direct: bool = True         # WAXAL_DIRECT: a listener that can turn Wolof speech straight into English does
    show_wolof: bool = False    # WAXAL_SHOW_WOLOF: also transcribe the Wolof, to show what was heard
    workers: int = 4            # WAXAL_WORKERS: turns of different people run in parallel, in this many processes
    # The folders.
    data: str = "data/users"
    documents: str = "data/documents"           # WAXAL_DOCUMENTS
    instructions: str = "data/instructions"     # WAXAL_INSTRUCTIONS_DIR
    skills: str = "data/skills"                 # WAXAL_SKILLS_DIR
    max_upload_bytes: int = 20 * MB             # WAXAL_MAX_UPLOAD_MB
    # The service.
    token: str | None = None    # WAXAL_TOKEN: protects the page and the API
    developer_mode: bool = False  # DEVELOPER_MODE: no S3, no WhatsApp
    cleanup: bool = True        # WAXAL_CLEANUP=off: no daily clean-up of old conversations and notes
    log_level: str = "INFO"     # WAXAL_LOG
    s3_bucket: str | None = None  # WAXAL_S3_BUCKET
    s3_shared_prefix: str = "documents/"
    s3_users_prefix: str = "users/"

    @classmethod
    def from_env(cls, env=None) -> "Settings":
        """The settings of an environment (os.environ by default). An empty variable is an unset one."""
        env = os.environ if env is None else env

        def get(name: str, default: str = "") -> str:
            return (env.get(name) or default).strip()

        return cls(
            language=Language.from_env(env),
            stt=get("WAXAL_STT", "elevenlabs").lower(),
            mt=get("WAXAL_MT", "claude").lower(),
            tts=get("WAXAL_TTS", "elevenlabs").lower(),
            direct=get("WAXAL_DIRECT", "on").lower() not in ("off", "0", "no"),
            show_wolof=get("WAXAL_SHOW_WOLOF").lower() in ("1", "on", "yes"),
            workers=int(get("WAXAL_WORKERS", "4")),
            documents=get("WAXAL_DOCUMENTS", "data/documents"),
            instructions=get("WAXAL_INSTRUCTIONS_DIR", "data/instructions"),
            skills=get("WAXAL_SKILLS_DIR", "data/skills"),
            max_upload_bytes=int(float(get("WAXAL_MAX_UPLOAD_MB", "20")) * MB),
            token=get("WAXAL_TOKEN") or None,
            developer_mode=get("DEVELOPER_MODE").lower() in _ON,
            cleanup=get("WAXAL_CLEANUP", "on").lower() not in _OFF,
            log_level=get("WAXAL_LOG", "INFO").upper(),
            s3_bucket=get("WAXAL_S3_BUCKET") or None,
            s3_shared_prefix=get("WAXAL_S3_SHARED_PREFIX", "documents/"),
            s3_users_prefix=get("WAXAL_S3_USERS_PREFIX", "users/"),
        )

    def with_(self, **changes) -> "Settings":
        """A copy with some settings changed (the command line's options over the environment's)."""
        from dataclasses import replace
        return replace(self, **changes)
