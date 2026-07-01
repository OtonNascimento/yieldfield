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
