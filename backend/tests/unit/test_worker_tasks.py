"""The worker registers tasks under exactly the names the API enqueues (spec §7)."""

from __future__ import annotations


def test_money_path_tasks_are_registered_under_the_api_contract_names() -> None:
    import yieldfield.workers.tasks  # noqa: F401 — importing registers the tasks
    from yieldfield.api.v1.dependencies.services import (
        INGEST_INVOICES_TASK,
        INGEST_USAGE_EVENTS_TASK,
        RUN_RECONCILIATION_TASK,
    )
    from yieldfield.workers.celery_app import celery_app

    registered = set(celery_app.tasks)
    assert {INGEST_INVOICES_TASK, INGEST_USAGE_EVENTS_TASK, RUN_RECONCILIATION_TASK} <= registered


def test_worker_boot_registers_tasks_without_manual_imports() -> None:
    # `celery -A yieldfield.workers.celery_app worker` imports only celery_app; without
    # `include` a real worker registers NO money-path tasks and every enqueue sits
    # PENDING forever — tests importing tasks explicitly had hidden this (audit WK-2).
    from yieldfield.workers.celery_app import celery_app

    assert "yieldfield.workers.tasks" in celery_app.conf.include


def test_beat_schedule_sweeps_stale_jobs_with_a_registered_task() -> None:
    import yieldfield.workers.tasks  # noqa: F401 — importing registers the tasks
    from yieldfield.workers.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["sweep-stale-jobs"]
    assert entry["task"] == "yieldfield.sweep_stale_jobs"
    assert entry["task"] in celery_app.tasks  # the schedule points at a real task
