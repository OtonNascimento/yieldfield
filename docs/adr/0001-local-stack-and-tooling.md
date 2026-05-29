# ADR 0001 — Local stack & tooling for the Slice 0 scaffold

**Status:** Accepted (2026-05-29)
**Governs:** Slice 0 of `docs/IMPLEMENTATION_PROMPT.md`
**Relates to:** PROJECT_CONTEXT §0 (locked, overridable decisions), §5 (stack), §15 (workflow), §16 (config)

## Context

PROJECT_CONTEXT §0 and §5 fix the *shape* of the stack (Python 3.12+/FastAPI, React/TS/Vite,
PostgreSQL for OLTP, a columnar store for OLAP, a queue + workers) but deliberately leave
several concrete choices open with `e.g.` lists. The columnar store is "ClickHouse or
BigQuery"; the async layer is "Celery/RQ or Temporal"; the Python dependency manager is
unspecified. Slice 0 requires a one-command local stack (`docker compose up`, §15), so these
open choices must be resolved concretely before scaffolding.

## Decision

These were confirmed with the project owner before scaffolding:

1. **Version control:** `git`, trunk = `main`, feature branches per slice (§15 trunk-based,
   small PRs). Slice 0 lands on branch `slice-0-scaffold`.
2. **Python dependency/tooling manager:** **uv** (manages the Python 3.12 toolchain, resolves
   and locks dependencies, drives Ruff/Black/mypy and the app/worker processes).
3. **Columnar (OLAP) store for local dev:** **ClickHouse.** BigQuery is not runnable in
   `docker compose`; ClickHouse satisfies §5/§12's columnar requirement locally and in CI.
   Production may still target a managed columnar store behind the same adapter (§12).
4. **Async/queue stack:** **Celery + Redis** (broker + result backend). Lightweight in
   compose, mature, and sufficient for ingestion/reconciliation/scoring jobs (§13). Temporal
   (named in §5 for multi-step orchestration) remains a future option behind the same
   `infrastructure/messaging/` seam and would get its own ADR if adopted.

## Consequences

- The columnar adapter (`infrastructure/analytics_store/`) and messaging adapter
  (`infrastructure/messaging/`) stay behind interfaces so ClickHouse→managed-OLAP and
  Celery→Temporal swaps do not ripple into domain/application/UI (§6.4, §17).
- The scaffold ships uv-based `pyproject.toml` + `uv.lock`, and compose runs api, workers,
  postgres, clickhouse, and redis.
- Reversing any of these requires a superseding ADR (§0).

## Status

Accepted. Supersedes nothing.
