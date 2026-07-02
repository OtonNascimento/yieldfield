# Slice 3D — Production Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Execution protocol is identical to Slice 3C: one task at a time, TDD first where applicable, full gates green after every task, one commit per task, independent code-quality review per task, clean tree before continuing.

**Goal:** Make the existing product production-ready by resolving the Important findings of the 2026-07-02 full engineering audit — no architecture changes, no product-scope expansion.

**Architecture:** Every change lands inside the existing seams: the Stripe adapter, `config/settings.py`, the compose/Docker layer, `run_as_job`/worker composition roots, the API dependency modules, and Alembic migrations. No new layers, no new external services (Redis/Postgres/ClickHouse remain the full stack).

**Tech stack:** unchanged — FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, Celery 5 + Redis, clickhouse-connect, structlog, uv.

**Source of truth:** `docs/audits/2026-07-02-full-engineering-audit.md`. Every finding referenced below was re-verified against `ca20ea8` on 2026-07-02 before this plan was written (grep/read evidence per finding; none refuted).

## Global constraints

- Run all gates from `backend/`: `uv run pytest -q`, `uv run mypy src tests`, `uv run ruff check .`, `uv run black --check .`, `uv run lint-imports`, and `uv run python ../ops/scripts/export_openapi.py --check` when the API surface changes.
- On this workstation every `uv` command needs `$env:UV_PYTHON='3.14'` (OS App Control blocks the pinned 3.12 toolchain locally; CI/Docker stay on 3.12).
- Commit messages follow the 3C convention: `type(scope): summary (§ref / audit-id)`.
- Import-linter contracts must stay 4/4; domain stays framework-pure; tenant never comes from a request body.
- Migrations are forward-only with working downgrades, numbered sequentially after `0002`.

---

## Finding disposition matrix

Every audit finding, its verification status, and its fate in this slice.

### Implement now

| Finding | Verified evidence | Task |
|---|---|---|
| SE-1 zero-decimal currencies silently ÷100 | `stripe_billing/mapping.py:29-30` | T1 |
| TE-2 non-USD/zero-decimal money untested | no test references `jpy`/zero-decimal | T1 |
| API-1 ingest(created) vs reconcile(period_start) window mismatch | `stripe_billing/connector.py:66-75` vs `persistence/repositories.py:133-143` | T2 |
| PR-1 no production config validation (+SE-6 debug/docs, PR-8 log_json) | `config/settings.py` has no validator; `main.py:32` passes `debug` through | T3 |
| PR-2 compose omits auth/cipher/flag envs | grep of `docker-compose.yml`: zero matches for `YIELDFIELD_API_TOKENS`, `CREDENTIALS_KEY`, `INGESTION_ENABLED` | T4 |
| M14 root containers, no api healthcheck | `infrastructure/docker/Dockerfile.api`, `docker-compose.yml:59-79` | T4 |
| PR-3 no migration/bootstrap step anywhere in the runtime path | Dockerfiles CMD straight to servers; compose has no init service; images don't even contain `ops/` | T5 |
| WK-2 orphaned PENDING jobs never swept | `services.py:116-118` documents the orphan; no `beat_schedule` anywhere | T6 |
| WK-1 poison redelivery loop unbounded | no `max_retries`/attempt tracking anywhere; `celery_app.py:26-28` | T7 |
| SE-2a no body cap on unauthenticated webhook | `api/webhooks/router.py:59` | T8 |
| SE-5 connector status never checked at ingress/build | `webhooks/router.py:55-57`, `registration.py:79-90` | T8 |
| TE-1 no end-to-end webhook test with a real signature | `tests/e2e/` contains only the 2 money-path tests | T8 |
| PR-5 engine never disposed; /ready builds engine per probe; no pool config | no `lifespan` in `main.py`; `readiness.py:24-33` | T9 |
| PR-4a no request/correlation IDs | no middleware beyond CORS in `main.py` | T10 |
| API-2 auth not an OpenAPI securityScheme | no `securitySchemes` in `contracts/openapi/openapi.json` | T11 |
| API-3 invalid cursor → generic `http_400` | `pagination.py:34-37` raises bare `HTTPException` | T11 |
| PF-4 missing composite indexes | `models.py`: only bare `tenant_id` indexes; migrations 0001/0002 create none | T12 |
| AR-2 misleading flush-ordering comment | `models.py:33-35` vs the E2E's forced `flush()` (`tests/e2e/test_money_path.py:96-98`) | T12 |
| TE-3 worker-side flag gate / foreign-connector failure unpinned | no test drives `workers/tasks.py` guards | T13 |
| TE-4 `_JOB_TYPE_BY_TASK` unknown-name behavior unpinned | `services.py:132` | T13 |
| PR-6 CI: no image builds, no dependency audit | `.github/workflows/ci.yml` — 4 jobs only | T14 |
| I-DOC product-correctness debts live only in docstrings | `run_reconciliation.py:9-12` | T15 |
| .env.example gaps; no migration runbook | `.env.example`; `ops/README.md` names no command | T15 |

### Defer (with justification)

| Finding | Justification |
|---|---|
| PF-1 reconciliation memory + plans N+1 | Worker-side only; no failure at current scale. The right fix (batch `list_for_customers` port + streamed usage) should be shaped by real load data. Tier: before-scale. |
| PF-2 unbounded lineage arrays | Capping lineage changes the auditability contract (§6.5) — a product decision, not a code fix. Needs explicit sign-off on count+sample semantics first. |
| PF-3 Stripe meters×customers N+1 | Connector-internal rework on the §17 growth axis; bounded by tenant size today; belongs with the second-connector work. |
| PF-5 ClickHouse `FINAL` cost | Same milestone as PF-1; correct today. |
| AR-1 duplicated API/worker composition | Pure refactor of two *sanctioned* composition roots, both pinned by tests; safest done when Slice 4 already touches DI. |
| AR-3 import-time app/log configuration | Conventional for uvicorn/celery entrypoints; invasive to change relative to benefit. |
| SE-2b request throttling | Edge/platform concern (`settings.py:44` documents the fronting assumption). T8 caps body size in-app; the throttle requirement is documented in the T15 runbook as a deployment prerequisite. |
| SE-3 static omnipotent tokens / OIDC | Explicit Slice-4 seam (`auth.py:3-5`); out of 3D scope by design. |
| SE-4 no row locking on jobs/reconciliations | Accepted §8 idempotent-convergence posture; T7's redelivery cap bounds the practical failure. `SELECT … FOR UPDATE` recorded as the eventual hardening. |
| WK-4 broker round-trip untested | Transport is Celery-core behavior; E2E pins the composition; a containerized worker test is CI-flake-prone. Covered by the staging smoke in the T15 runbook. |
| API-4 full-tenant loads behind opaque cursors | Same milestone as PF-1/PF-5 (keyset pagination); the wire contract already isolates the change to `pagination.py` + repo queries — no interface debt accrues by waiting. |
| TE-5 testcontainers `wait_for_logs` deprecation / container-timing flake surface | No observed flakes; the deprecation breaks only on a future testcontainers major bump, which is when the structured wait-strategy swap belongs (it is mechanical). |
| API-5 `version="0.0.0"` | Needs a release convention (product decision); zero code risk before external consumers exist. |
| PR-4b metrics / tracing / error tracker | Vendor and platform choices belong to the deployment slice (k8s/terraform are still placeholders). T10 lands the zero-dependency, highest-leverage piece (correlation IDs). |

### Reject (with evidence)

| Finding | Evidence for rejection |
|---|---|
| PR-7 local 3.14 vs pinned 3.12 drift | Not a repository defect: `backend/.python-version` (tracked) pins 3.12 consistently with CI and Dockerfiles; CI is green on 3.12. The drift exists only on this workstation (OS App Control blocks uv's 3.12 shims). Noted in the T15 runbook; no repo change can fix a local OS policy. |
| WK-3 job listing/cancellation | Feature expansion — explicitly barred by the 3D charter ("no new features unless required to resolve an audited production-readiness issue"); polling known job ids is sufficient for current operations. |
| M16 `db_session` commits on reads | `database.py:26` commit on a read-only session is a no-op round-trip; branching per-verb adds complexity for zero measurable benefit. |

---

## Tasks

Execution note (3C convention): each task below fixes scope, files, approach, and its test plan. The implementer expands each into RED→GREEN steps against the live repo at execution time; where a design decision is non-obvious the exact code is given here and is binding.

### Phase A — Critical correctness

#### Task 1: Fail loudly on non-two-decimal Stripe currencies (SE-1, TE-2)

**Files:** Modify `backend/src/yieldfield/infrastructure/connectors/stripe_billing/mapping.py`; Test `backend/tests/unit/test_stripe_mapping.py` (extend the existing mapping tests).
**Impact:** ~40 LoC. No API/contract change.

Binding design — allowlist + loud failure in `_money_from_minor`:

```python
# ISO-4217 two-decimal currencies this mapper can convert exactly. Stripe reports
# zero-decimal currencies (JPY, KRW, …) in whole units; converting them here with
# /100 would be silently wrong by 100x — so anything not listed fails loudly (§7).
_TWO_DECIMAL_CURRENCIES = frozenset({"USD", "EUR", "GBP", "CAD", "AUD", "NZD", "CHF", "SGD", "HKD", "SEK", "NOK", "DKK", "PLN", "CZK", "MXN", "BRL", "ZAR", "INR", "AED", "SAR"})

def _money_from_minor(amount: Any, currency: str) -> Money:
    code = currency.upper()
    if code not in _TWO_DECIMAL_CURRENCIES:
        raise ConnectorError(
            f"Unsupported currency {code!r}: only two-decimal currencies are converted "
            f"exactly; extend the allowlist deliberately (§7 fail-loud)."
        )
    return Money(Decimal(int(amount)) / _MINOR_UNITS, code)
```

(`ConnectorError` import from `...connectors.base.connector`; a failed ingest surfaces as a FAILED job with this message — the correct §3 behavior.)

TDD: RED — `test_zero_decimal_currency_fails_loudly` (`jpy` invoice line → `pytest.raises(ConnectorError, match="JPY")`) and `test_two_decimal_currency_converts_exactly` (eur 1234 → `Money("12.34","EUR")`); GREEN — implement; verify the existing usd tests still pass.

#### Task 2: Align ingest and reconcile window semantics (API-1)

**Files:** Modify `backend/src/yieldfield/infrastructure/connectors/stripe_billing/connector.py:64-94`; Modify `backend/src/yieldfield/api/v1/schemas/ingestion.py` (docstring only); Test `backend/tests/unit/test_stripe_connector_unit.py` + `backend/tests/integration/test_stripe_connector_integration.py` (assert filtering).
**Impact:** ~60 LoC. Ingestion semantics become "invoices whose *period overlaps* the window" — strictly more correct; no schema change.

Binding design — pad the Stripe `created` scan, filter client-side by period overlap:

```python
# Stripe cannot filter invoices by billing period, only by creation time. Invoices
# finalize after their period (arrears) or before it (upfront), so scan a padded
# created-range and keep exactly those whose PERIOD overlaps the window — making
# "window" mean the same thing here as in reconciliation reads (§13).
_CREATED_SCAN_PAD = timedelta(days=45)

# in pull_invoices:
params={"created": {
    "gte": int((window.start - _CREATED_SCAN_PAD).timestamp()),
    "lt": int((window.end + _CREATED_SCAN_PAD).timestamp()),
}, ...}
...
invoice = invoice_from_stripe(self._tenant_id, raw)
if invoice.period.overlaps(window):
    yield invoice
```

TDD: unit test with a fake paging client — an invoice created outside the window but with an overlapping period is yielded; an invoice created inside the window whose period does not overlap is dropped. Note in the plan doc + `IngestionRequest` docstring: reconciliation still selects by `period_start ∈ window` (unchanged product semantics, now documented).

### Phase B — Production configuration

#### Task 3: Production settings validator (PR-1, SE-6, PR-8)

**Files:** Modify `backend/src/yieldfield/config/settings.py`; Test `backend/tests/unit/test_settings.py` (create if absent).
**Impact:** ~50 LoC. Boot-time behavior change in production only.

Binding design:

```python
@model_validator(mode="after")
def _production_invariants(self) -> Settings:
    """Fail at boot, not on first request, when production is misconfigured (§16)."""
    if self.environment != "production":
        return self
    problems = [
        name for name, ok in [
            ("YIELDFIELD_DATABASE_URL", bool(self.database_url)),
            ("YIELDFIELD_CLICKHOUSE_URL", bool(self.clickhouse_url)),
            ("YIELDFIELD_CREDENTIALS_KEY", bool(self.credentials_key)),
            ("YIELDFIELD_API_TOKENS", bool(self.api_tokens)),
            ("YIELDFIELD_LOG_JSON=true", self.log_json),
            ("YIELDFIELD_DEBUG=false", not self.debug),
            ("YIELDFIELD_CONNECTOR_BASE_URL unset", self.connector_base_url is None),
        ] if not ok
    ]
    if problems:
        raise ValueError(f"Production misconfiguration: {', '.join(problems)} (§16).")
    return self
```

TDD: RED — `environment="production"` with defaults raises listing every missing key; a fully-configured production Settings passes; local defaults unaffected.

#### Task 4: Compose serves a working system; container hardening (PR-2, M14)

**Files:** Modify `docker-compose.yml` (`&backend-env` block + api healthcheck), `infrastructure/docker/Dockerfile.api`, `infrastructure/docker/Dockerfile.worker` (non-root `USER`).
**Impact:** config-only; no Python changes.

Compose env additions (pass-through with safe local defaults):

```yaml
      YIELDFIELD_API_TOKENS: ${YIELDFIELD_API_TOKENS:-{"local-dev-token":"tenant-local"}}
      YIELDFIELD_CREDENTIALS_KEY: ${YIELDFIELD_CREDENTIALS_KEY:-}
      YIELDFIELD_INGESTION_ENABLED: ${YIELDFIELD_INGESTION_ENABLED:-false}
      YIELDFIELD_CONNECTOR_BASE_URL: ${YIELDFIELD_CONNECTOR_BASE_URL:-}
```

api healthcheck (no curl in slim images): `test: ["CMD", "python", "-c", "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/v1/health')"]` — note: must run as the venv's python; use `uv run python -c ...`. Dockerfiles: create `app` user after installs, `USER app`. Verification gate: `docker compose config -q` + both images build.

#### Task 5: Migrations + ClickHouse bootstrap on stack init (PR-3)

**Files:** Modify `infrastructure/docker/Dockerfile.api` (add `COPY ops/ ./ops/` so the image can run Alembic), `docker-compose.yml` (one-shot `migrate` service; api/worker `depends_on: migrate: condition: service_completed_successfully`), `ops/README.md` (runbook).
**Impact:** config + docs. Build-context note: Dockerfile context is repo root, so the COPY is legal.

`migrate` service (uses the api image):

```yaml
  migrate:
    build: {context: ., dockerfile: infrastructure/docker/Dockerfile.api}
    environment: *backend-env
    command: >
      sh -c "uv run alembic -c ops/migrations/alembic.ini upgrade head
             && uv run python ops/scripts/bootstrap_clickhouse.py"
    depends_on:
      postgres: {condition: service_healthy}
      clickhouse: {condition: service_healthy}
```

Pre-flight at execution: confirm `alembic.ini`'s `script_location` resolves relative to the ini file (it lives at `ops/migrations/alembic.ini`) and that `bootstrap_clickhouse.py` reads `YIELDFIELD_CLICKHOUSE_URL`; adapt the command if either differs. **Verification: one full `docker compose up` smoke — `/api/v1/ready` must return 200 with postgres/clickhouse/redis all "ok"** (this also proves T4). Document the same two commands as the non-compose runbook in `ops/README.md`.

### Phase C — Reliability

#### Task 6: Stale-PENDING sweeper (WK-2)

**Files:** Modify `backend/src/yieldfield/infrastructure/persistence/repositories.py` (`SqlAlchemyJobRepository.list_stale_pending(cutoff: datetime) -> Sequence[Job]` — cross-tenant *operational* read, documented in place like `find_by_id`), `backend/src/yieldfield/workers/tasks.py` (task `yieldfield.sweep_stale_jobs`: mark each stale PENDING job FAILED with error `"stale: never picked up within {n} minutes"`), `backend/src/yieldfield/workers/celery_app.py` (`beat_schedule`: hourly), `backend/src/yieldfield/config/settings.py` (`job_pending_timeout_minutes: int = 360`); Tests: unit (fake ledger: stale PENDING → FAILED; fresh PENDING and RUNNING untouched) + integration (repo query filters by status+cutoff only).
**Impact:** ~120 LoC. Requires running beat in deployment (`celery -B` or beat service) — documented in T15 runbook + compose worker command gains `-B`.

#### Task 7: Redelivery cap in run_as_job (WK-1)

**Files:** Create `ops/migrations/versions/0003_jobs_attempts.py` (`attempts INTEGER NOT NULL DEFAULT 0` on `jobs`, with downgrade); Modify `backend/src/yieldfield/infrastructure/persistence/job.py` (field `attempts: int = 0`), `models.py`, `repositories.py` (row mapping), `backend/src/yieldfield/infrastructure/messaging/run_as_job.py`; Tests: `tests/unit/test_run_as_job.py` (extend), integration migration test count.
**Impact:** ~100 LoC + migration.

Binding semantics: on entry, if the job is non-terminal and `job.attempts >= MAX_DELIVERY_ATTEMPTS` (=3), mark FAILED (`error="exceeded max delivery attempts"`) + commit + log + return (no re-raise — the message is consumed). Otherwise persist `attempts=job.attempts+1` as part of the RUNNING transition. Existing redelivery-noop and choreography pins must stay green unchanged.

#### Task 8: Webhook hardening + real-signature E2E (SE-2a, SE-5, TE-1)

**Files:** Modify `backend/src/yieldfield/api/webhooks/router.py` (reject `Content-Length` > 512 KiB and measured body > 512 KiB with 413 via a typed `WebhookPayloadTooLargeError` → envelope code `payload_too_large`; treat `connector.status is not ConnectorStatus.ACTIVE` exactly like not-found → 404), `backend/src/yieldfield/api/errors/exceptions.py` + `handlers.py` (the new typed error), `backend/src/yieldfield/infrastructure/connectors/registration.py` (`build_authenticated` raises `ConnectorError` for non-ACTIVE — defense in depth for the worker path); Create `backend/tests/e2e/test_webhook_path.py` (register via API with a real `whsec` → build a genuine Stripe signature header (same HMAC helper as `test_stripe_connector_unit.py`) → POST `/api/v1/webhooks/{id}` → 202 → job SUCCEEDED via eager queue against stripe-mock); extend `tests/unit/test_webhooks_router.py` (oversize → 413 nothing enqueued; disabled connector → 404 nothing enqueued).
**Impact:** ~150 LoC. Throttling explicitly deferred to the edge (see disposition matrix).

#### Task 9: Engine lifecycle + readiness reuse + pool config (PR-5)

**Files:** Modify `backend/src/yieldfield/api/v1/dependencies/database.py` (expose the cached engine; add `dispose_engine()`), `backend/src/yieldfield/api/main.py` (lifespan context disposing on shutdown), `backend/src/yieldfield/api/v1/dependencies/readiness.py` (`_check_postgres` uses the process engine instead of building one per probe), `backend/src/yieldfield/infrastructure/persistence/engine.py` + `config/settings.py` (`db_pool_size: int = 5`, `db_max_overflow: int = 10` → `create_engine(pool_size=…, max_overflow=…)`); Tests: readiness monkeypatch pins unchanged; new unit pin that `_check_postgres` does not construct a new engine (fake factory records calls).
**Impact:** ~80 LoC.

### Phase D — Observability

#### Task 10: Request-ID + tenant log context (PR-4a)

**Files:** Create `backend/src/yieldfield/api/middleware.py` (pure-ASGI-level Starlette middleware: read `X-Request-ID` or mint `uuid4`; `structlog.contextvars.clear_contextvars()` + `bind_contextvars(request_id=…)`; echo the header on the response; one `log.info("http.request", method, path, status, duration_ms)` per request); Modify `main.py` (register), `dependencies/auth.py` (`bind_contextvars(tenant_id=…)` on successful resolution); Test `backend/tests/unit/test_request_context.py` (response carries `X-Request-ID`; supplied id is echoed; log record carries it — capture via structlog testing capture).
**Impact:** ~120 LoC. Metrics/tracing/Sentry stay deferred (PR-4b).

### Phase E — API contract

#### Task 11: Bearer securityScheme + semantic cursor error (API-2, API-3)

**Files:** Modify `backend/src/yieldfield/api/v1/dependencies/auth.py` (swap the raw `Header()` for `fastapi.security.HTTPBearer(auto_error=False)` via `Security(...)` — same 401 `unauthorized` envelope on all existing failure cases; existing pins in `test_api_dependencies.py` must pass with at most mechanical signature updates), `pagination.py` (raise new `InvalidCursorError` instead of bare `HTTPException`), `errors/exceptions.py` + `errors/handlers.py` (map → 400 `invalid_cursor`), regenerate `contracts/openapi/openapi.json` (now contains `components.securitySchemes.HTTPBearer` and per-route `security`); Tests: extend `test_openapi_contract.py` (`securitySchemes` present), cursor pins updated to assert `error.code == "invalid_cursor"`.
**Impact:** ~80 LoC + contract regeneration (drift gate must pass).

### Phase F — Performance

#### Task 12: Composite indexes + flush-comment fix (PF-4, AR-2)

**Files:** Create `ops/migrations/versions/0004_reconciliation_read_indexes.py` (`ix_invoices_tenant_period_start (tenant_id, period_start)`, `ix_contracts_tenant_customer (tenant_id, customer_id)`, with downgrades); Modify `models.py` (`__table_args__ = (Index(...),)` on `InvoiceRow`/`ContractRow` to keep ORM DDL parity; correct the `TenantRow` relationship comment at `models.py:33-35` to claim only tenant→child ordering); integration migration test updated for the new head.
**Impact:** ~60 LoC.

### Phase G — Test hardening

#### Task 13: Worker composition pins (TE-3, TE-4)

**Files:** Extend `backend/tests/unit/test_worker_tasks.py` — monkeypatch `workers.tasks._session_factory`/`_usage_event_store` with fakes: (a) `ingest_invoices_task` with `YIELDFIELD_INGESTION_ENABLED=false` → job FAILED, error mentions the flag; (b) foreign/unknown connector id → job FAILED via `ConnectorError`, no cross-tenant read; (c) pin that `_JOB_TYPE_BY_TASK` covers exactly the three exported task-name constants so a new route/name cannot silently 500 (`services.py:100-104`).
**Impact:** tests only, ~120 LoC.

### Phase H — CI & documentation

#### Task 14: CI hardening (PR-6)

**Files:** Modify `.github/workflows/ci.yml` — new `images` job (`docker build` both backend Dockerfiles, no push; catches Dockerfile rot — depends on T4/T5 being merged) and a `dependency-audit` job (`uvx pip-audit` against `backend/uv.lock` export + `npm audit --audit-level=high` in `frontend/`), both `continue-on-error: true` initially with an inline comment stating the flip-to-blocking condition (first triage complete).
**Impact:** CI-only.

#### Task 15: Documentation + debt promotion (I-DOC, PR-8, runbook)

**Files:** Modify `ops/README.md` (runbook: migration/bootstrap commands for compose and bare-metal; staging smoke checklist including one real broker round-trip (WK-4) and the edge-throttle prerequisite (SE-2b)); `.env.example` (add `YIELDFIELD_DEBUG`, `YIELDFIELD_API_HOST/PORT`, `YIELDFIELD_JOB_PENDING_TIMEOUT_MINUTES`, pool settings; note the production validator); `docs/IMPLEMENTATION_PROMPT.md` (new "Known product-correctness debts" entries with explicit triggers: un-invoiced customers produce no findings; contract terms ignored in plan attribution — both cite `run_reconciliation.py`).
**Impact:** docs-only.

---

## Order rationale

1. **Correctness before everything (T1–T2):** wrong money must not survive another slice; both fixes are self-contained in the Stripe adapter and independent of all later work.
2. **Configuration next (T3–T5):** these unblock an honest, runnable stack; T5's compose-up smoke is the integration proof for T3+T4, and every later task benefits from a deployable baseline. T4 must precede T5 (the migrate service reuses the fixed image/env) and both must precede T14 (CI builds those Dockerfiles).
3. **Reliability (T6–T9):** behavior changes (sweeper, attempts cap, webhook 413/404, lifecycle) land before observability so T10's logging reports final behavior; T7's migration 0003 precedes T12's 0004 in the Alembic chain.
4. **Observability (T10) then contract (T11):** middleware settles the request path before the auth dependency swap; T11 regenerates the committed contract exactly once, after all surface-affecting work, and is the Slice-4 codegen prerequisite.
5. **Indexes (T12) late but pre-data:** cheap while tables are empty; sequenced only by migration numbering.
6. **Tests (T13) and CI/docs (T14–T15) last:** they pin and document the finished state; T14's image-build job would fail if run before T4/T5.

**Total estimated impact:** 15 tasks, ~1,150 LoC touched (≈half tests), 2 new migrations, 1 contract regeneration, 3 config files, 0 architecture changes, 0 new runtime dependencies.

## Verification (slice-level, after T15)

- Full gates green from `backend/` (pytest incl. Docker integration+E2E, mypy, ruff, black, lint-imports, OpenAPI drift).
- `docker compose up` from a clean checkout + `.env` → `/api/v1/ready` 200 all-ok; registered connector + webhook with real signature → job SUCCEEDED.
- `git log`: exactly one commit per task (+review-fix commits where reviews demand them); clean tree.
