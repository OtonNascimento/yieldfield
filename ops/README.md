# ops/

Operational tooling (§12, §15).

- `migrations/` — versioned, **forward-only** DB migrations (Alembic, wired in Slice 2).
- `seeds/` — deterministic seed data for local/staging.
- `scripts/` — maintenance and one-off operational scripts.

## Applying the schema (audit PR-3)

A fresh stack has **no tables** until both steps below run. The compose stack runs them
automatically via the one-shot `migrate` service (api/worker wait for it); every other
environment runs the same two commands before starting servers:

```bash
# from backend/ (the uv project) — needs YIELDFIELD_DATABASE_URL + YIELDFIELD_CLICKHOUSE_URL
uv run alembic -c ../ops/migrations/alembic.ini upgrade head
uv run python ../ops/scripts/bootstrap_clickhouse.py
```

Migrations are forward-only in shared environments: never `downgrade` against data you
cannot recreate. Downgrades exist for local development and CI verification.

## Staging smoke checklist (run against every freshly deployed stack)

CI proves everything except the broker transport (unit/E2E tests run Celery eagerly,
audit WK-4). This checklist closes that gap with a real worker behind a real broker.

1. **Readiness** — `GET /api/v1/ready` returns 200 with every dependency `ok`
   (postgres, clickhouse, redis). A non-200 names the failing dependency.
2. **Broker round-trip (WK-4 — the one path no test exercises)** — with the real
   worker and beat running (never `task_always_eager`):
   register a connector (`POST /api/v1/connectors`), submit
   `POST /api/v1/ingestion/invoices` for a window, then poll
   `GET /api/v1/jobs/{job_id}` until `succeeded`. A job stuck `pending` means the
   worker registered no tasks or cannot reach Redis; `failed` carries the error.
3. **Signed webhook** — POST a genuinely HMAC-signed payload to
   `/api/v1/webhooks/{connector_id}` → 202 and the job reaches `succeeded`; the same
   payload with one flipped byte → 400 `invalid_webhook_signature`.
4. **Stale-job sweep** — confirm beat schedules `sweep-stale-jobs` (hourly): a PENDING
   job older than `YIELDFIELD_JOB_PENDING_TIMEOUT_MINUTES` must flip to `failed`.

## Production prerequisites

- **Edge throttling (audit SE-2b)** — the app enforces a 512 KiB webhook body cap but
  deliberately no request throttling (`settings.py` documents the fronting assumption).
  The platform in front of the API (ingress / API gateway / CDN) MUST rate-limit
  before the API is exposed publicly.
- **Production settings validator (§16)** — with `YIELDFIELD_ENVIRONMENT=production`
  the process refuses to boot unless `DATABASE_URL`, `CLICKHOUSE_URL`,
  `CREDENTIALS_KEY`, and `API_TOKENS` are set, `LOG_JSON=true`, `DEBUG=false`, and
  `CONNECTOR_BASE_URL` is unset. Treat a boot failure here as a deploy error.
- **Dependency-audit triage (audit PR-6)** — CI's audit jobs are advisory
  (`continue-on-error: true`). Flip them to blocking after resolving the initial
  findings (as of 2026-07-04): backend — cryptography 48.0.0→48.0.1,
  pydantic-settings 2.14.1→2.14.2, starlette 1.2.0→1.3.1; frontend — vitest
  (critical), vite, form-data, js-yaml (`npm audit fix`).

## Known follow-ups

- The bare `tenant_id` indexes on `invoices`/`contracts` are leading-prefix-redundant
  with the 0004 composites; drop them in a later migration to halve index write
  amplification on the two ingest-heavy tables (T12 review note).

## Local-dev note: pinned Python vs OS policy (audit PR-7)

`backend/.python-version` pins 3.12 — CI and the Docker images build against it. If
the workstation's OS policy (e.g. Windows App Control) blocks uv-managed interpreters,
run every uv command with `UV_PYTHON` pointed at an allowed system Python (this repo's
sessions use `UV_PYTHON=3.14`); otherwise uv rebuilds the venv against the blocked
toolchain. This is a machine-local workaround, not a repo setting.
