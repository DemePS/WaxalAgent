"""Builds the core of a run from its Settings: the engines, the agent (or the pool of agents), the pipeline. No web framework in here: a script,
a queue worker or the web server (waxal_server) all start from build_pipeline."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .pipeline import Pipeline
from .settings import Settings


def _stderr(message: str) -> None:
    print(message, file=sys.stderr)


@dataclass
class Runtime:
    """What a front end (the web server, a worker...) needs to serve people: the pipeline, the library of documents, the WhatsApp bot (or None)."""

    settings: Settings
    pipeline: Pipeline
    files: "object"          # files.Library: the documents the people upload
    bot: "object | None" = None   # whatsapp.WhatsAppBot, when WhatsApp is on
    s3: "object | None" = None    # s3_sync.S3Documents, when the documents come from S3


def build_pipeline(settings: Settings | None = None, refresh=None) -> Pipeline:
    """The pipeline of a run. `refresh(user_id)`: called before a person's turn to bring their files up to date (S3)."""
    from .agent import AgentTurns
    from .engines import build_engines
    settings = settings or Settings.from_env()
    listener, translator, speaker = build_engines("hosted", settings)
    if settings.workers > 1:  # turns of different people run in parallel, in separate processes
        from .agent_pool import AgentPool
        agent = AgentPool(settings.workers, settings.data, settings.documents, refresh, instructions=settings.instructions,
                          skills=settings.skills, language=settings.language, log_level=settings.log_level)
    else:
        agent = AgentTurns(settings.data, documents=settings.documents, refresh=refresh, instructions=settings.instructions,
                           skills=settings.skills, language=settings.language)
    return Pipeline(listener, translator, speaker, agent, language=settings.language, direct=settings.direct, show_wolof=settings.show_wolof)


def build_runtime(settings: Settings | None = None, whatsapp: bool = False, say: Callable[[str], None] = _stderr) -> Runtime:
    """Everything a front end needs, started: the daily clean-up, the system certificates, S3, the pipeline, the library, the WhatsApp bot.
    `say`: where the start-up report goes (stderr by default). No web framework in here."""
    from . import browsing, certs, maintenance
    from .agent import skills_report
    from .engines import describe_engines
    from .files import Library
    settings = settings or Settings.from_env()
    maintenance.start(enabled=settings.cleanup)  # old conversations and notes: once now, then daily
    certs.trust_system_certificates()  # a company proxy re-signs HTTPS (models, Meta)
    language = settings.language
    used = describe_engines("hosted", settings)
    say(f"Engines: recognition: {used['stt']}, translation: {used['mt']}, voice: {used['tts']}")
    say(f"The agent works and answers in: {language.reply_language}"
        + (f" (nothing is translated: the agent reads and writes {language.name})" if not language.translating
           else f" (translated into Wolof by {used['mt']})"))
    if not language.translating and language.reply_language != "wo" and settings.stt == "soynade":
        say("Warning: Soynade recognises Wolof only: with no translation and a language other than Wolof, use WAXAL_STT=elevenlabs.")
    s3 = None
    if settings.s3_bucket and not settings.developer_mode:
        from .s3_sync import S3Documents, s3_client
        s3 = S3Documents(s3_client(), settings.s3_bucket, settings.s3_shared_prefix, settings.s3_users_prefix)
        s3.start(Path(settings.documents))
        say(f"The documents come from S3 (bucket {s3.bucket}); the library is synced every {s3.interval:.0f} s.")
    elif settings.s3_bucket:
        say("DEVELOPER_MODE: S3 is off, the documents are read from the local folders.")
    pipeline = build_pipeline(settings, refresh=s3.refresh_user if s3 else None)
    say(skills_report(getattr(pipeline.agent, "skills", None)))
    say(browsing.report())
    files = Library(settings.documents, settings.max_upload_bytes)
    bot = None
    if whatsapp and settings.developer_mode:
        say("DEVELOPER_MODE: WhatsApp is off, only the test page is served.")
    elif whatsapp:
        from .whatsapp import WhatsAppBot, WhatsAppClient, WhatsAppConfig
        config = WhatsAppConfig.from_env()
        bot = WhatsAppBot(pipeline, WhatsAppClient(config), config)
        bot.files = files
        if not config.allowed:
            say("Warning: WAXAL_ALLOWED is empty: nobody can use the agent yet.")
    return Runtime(settings, pipeline, files, bot, s3)
