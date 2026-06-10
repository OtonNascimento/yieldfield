"""Task-queue seam (spec §7): the API enqueues Celery tasks BY NAME via `send_task`,
so it never imports task functions — and tests fake this Protocol instead of a broker."""

from __future__ import annotations

from typing import Annotated, Protocol, cast

from fastapi import Depends


class TaskQueue(Protocol):
    def enqueue(self, task_name: str, *args: str) -> str:
        """Queue `task_name` with string args; return the broker task id."""
        ...


class CeleryTaskQueue:
    def enqueue(self, task_name: str, *args: str) -> str:
        # Deferred import: broker config is read at enqueue time, not at app import.
        from yieldfield.workers.celery_app import celery_app

        return cast(str, celery_app.send_task(task_name, args=list(args)).id)


def get_task_queue() -> TaskQueue:
    return CeleryTaskQueue()


TaskQueueDep = Annotated[TaskQueue, Depends(get_task_queue)]
