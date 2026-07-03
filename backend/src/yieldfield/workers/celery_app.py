"""Celery application — the async worker entrypoint (§13, ADR-0001).

Long-running ingestion/reconciliation/scoring jobs run here, out of band from the
API tier, so the request path stays stateless (§9). Slice 0 ships only the app and a
trivial `ping` task to prove the worker boots and the broker round-trips; real tasks
arrive with the application use-cases in Slice 3. Run with:
`celery -A yieldfield.workers.celery_app worker --loglevel=info`.
"""

from __future__ import annotations

from celery import Celery

from yieldfield.config.logging import configure_logging
from yieldfield.config.settings import get_settings

settings = get_settings()
configure_logging(settings)

celery_app = Celery(
    "yieldfield",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    # Load-bearing: `celery -A yieldfield.workers.celery_app worker` imports only THIS
    # module — without `include`, a real worker registers no money-path tasks at all
    # and every enqueue sits PENDING forever (tests import tasks explicitly, hiding it).
    include=["yieldfield.workers.tasks"],
)
celery_app.conf.update(
    task_acks_late=True,  # resumable/idempotent posture for money-path jobs (§13)
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    enable_utc=True,
    # Periodic maintenance (audit WK-2): the compose worker runs with -B; multi-worker
    # deployments must run exactly one beat process.
    beat_schedule={
        "sweep-stale-jobs": {"task": "yieldfield.sweep_stale_jobs", "schedule": 3600.0},
    },
)


@celery_app.task(name="yieldfield.ping")  # type: ignore[untyped-decorator]  # Celery decorator is untyped
def ping() -> str:
    """Smoke task: confirms the worker and broker are wired. Not business logic."""
    return "pong"
