"""Celery application for the async ingestion pipeline (plan section 2,
phase 1: infra foundation). Redis is both broker and result backend --
one fewer moving part than a separate result store, and fine at MVP scale.

Real pipeline tasks (text extraction, chunking/embedding, entity/relation
extraction) get added to `pipeline.py` in later phases; this module only
owns the Celery app instance + config so the api, celery_worker, and
celery_beat processes (see docker-compose.yml) all import the same app.
"""
from celery import Celery
from .. import entities  # noqa: F401 -- registers all entities on Base.metadata; see entities/__init__.py
from ..config import get_settings

settings = get_settings()

celery_app = Celery(
    "clean_architecture",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["src.tasks.pipeline"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # `batch_extract_entities` (phase 7, spec 2.5) is the only scheduled
    # job for now; the crawling module (phase 5, section 2.3's "scheduled
    # re-crawl") will add its own entry here once it exists.
    beat_schedule={
        "batch-extract-entities": {
            "task": "pipeline.batch_extract_entities",
            "schedule": settings.entity_extraction_batch_interval_seconds,
        },
    },
)
