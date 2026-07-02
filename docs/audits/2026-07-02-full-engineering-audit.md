# Yieldfield — Full Engineering Audit

**Date:** 2026-07-02 · **Branch:** `slice-3-application-api-jobs` @ `ca20ea8` (73 commits / +20,609 −23 lines over `main`)
**Scope:** entire repository; backend at full depth, frontend as a state assessment.
**Method:** evidence-first Senior-Staff-Engineer review. Every claim was re-derived from source (prior reviews treated as hypotheses); every finding cites `file:line`. Verification commands were re-run first-hand.

---

## 0. Evidence baseline (re-run 2026-07-02)

| Gate | Result |
|---|---|
| `pytest` (full: unit + Docker integration + E2E) | **281 passed, 1 skipped** (env-gated live-Stripe test), 13 warnings, 104 s |
| `mypy src tests` (strict) | Success — 162 source files |
| `ruff check .` | All checks passed |
| `black --check .` | 162 files unchanged |
| `lint-imports` | 4 contracts kept, 0 broken |
| `export_openapi.py --check` | OpenAPI contract up to date |

Caveat: local verification ran on Python **3.14.6** (this machine's Application Control policy blocks uv's pinned 3.12 toolchain), while `backend/.python-version`, CI, and the Docker images pin **3.12** — see finding PR-7.

**Verdict up front:** the codebase is architecturally excellent and financially careful, with an unusually disciplined test culture. It is **not yet production-deployable**: the deployment/config layer (compose env, migrations-on-boot, prod config validation, observability) is one slice behind the code. No Critical findings; no exploitable cross-tenant path, injection, or auth bypass was found.

---

## 1. Architecture — strong; enforced, not just documented

**What holds (verified):**
- The domain layer is genuinely framework-pure and the rule is *enforced in CI*, not aspirational: four import-linter contracts ([backend/pyproject.toml:115-163](../../backend/pyproject.toml)) all kept, `.github/workflows/ci.yml:37-38` runs them on every PR.
- Dependencies point inward everywhere sampled: routers are thin adapters (validate → use-case → serialize, e.g. [findings.py](../../backend/src/yieldfield/api/v1/routers/findings.py), [jobs.py](../../backend/src/yieldfield/api/v1/routers/jobs.py)); composition is confined to `api/v1/dependencies/`, `api/webhooks/`, and `workers/tasks.py`; the single sanctioned exception (the `ConnectorAuthError` **type** import in [handlers.py:31](../../backend/src/yieldfield/api/errors/handlers.py)) is documented in place.
- Ports are Protocols at the right altitude (domain repositories; infrastructure-owned `ConnectorStore` in [registration.py:27-41](../../backend/src/yieldfield/infrastructure/connectors/registration.py) with the rationale for *why* it is not a domain port written where the decision lives).
- The layout matches `docs/ARCHITECTURE.md` table-for-table; stub packages (`notifications/`, `scoring_engine/`, `alerting/`, `metronome|orb|lago` absent) are consistent with the slice roadmap, not dead weight.

**Findings:**

| ID | Sev | Finding |
|---|---|---|
| AR-1 | Minor | **Duplicated composition logic** — `_cipher`/registration wiring exists twice: [api/v1/dependencies/services.py:52-67](../../backend/src/yieldfield/api/v1/dependencies/services.py) and [workers/tasks.py:65-75](../../backend/src/yieldfield/workers/tasks.py) (`_registration`), plus two `ingestion_enabled` guards ([routers/ingestion.py:27-31](../../backend/src/yieldfield/api/v1/routers/ingestion.py), [workers/tasks.py:78-80](../../backend/src/yieldfield/workers/tasks.py)). The API/worker pairs must stay semantically identical by hand. *Why it matters:* maintainability — a cipher or base-url change applied to one side silently diverges the other. *Smallest fix:* extract one shared factory module consumed by both composition roots (worker flag guard staying a deliberate re-check is fine). *Class:* technical debt. |
| AR-2 | Minor | **Misleading flush-ordering comment** — [models.py:33-35](../../backend/src/yieldfield/infrastructure/persistence/models.py) claims the `TenantRow` relationships make the unit-of-work respect FK ordering for same-session bulk adds, but nothing orders `contracts` after `plans` (no relationship on `ContractRow.plan_id`); the E2E had to add an explicit `flush()` for exactly this ([tests/e2e/test_money_path.py:96-98](../../backend/tests/e2e/test_money_path.py)). *Fix:* correct the comment or add the `plan` relationship. *Class:* documentation gap. |
| AR-3 | Future | `main.py:59` (`app = create_app()`) and [celery_app.py:17-18](../../backend/src/yieldfield/workers/celery_app.py) run settings + logging configuration at import time. Conventional for uvicorn/celery targets, but it makes any import of these modules side-effectful (tests already work around it). Consider lazy app factories only. *Class:* technical debt. |

SOLID/DRY/KISS/YAGNI: no violations worth reporting beyond AR-1. The codebase is conspicuously *not* over-engineered; abstractions exist exactly where a seam is named (§17).

---

## 2. Security — sound for the slice's threat model; three gaps to close before real tenants

**What holds (verified fresh):**
- **Tenant isolation**: every repository read filters `tenant_id` in SQL ([repositories.py:74-78, 96-101, 126-131, 159-176, 183-210, 230-245, 306-323](../../backend/src/yieldfield/infrastructure/persistence/repositories.py)); every write passes the `_guard` (line 47-51); `JobRepository.update` re-checks row tenancy (315-316). The single non-tenant-scoped read (`find_by_id`, 256-261) is the webhook routing key, documented in place, and the signature is the authentication. ClickHouse queries parameterize `tenant_id` ([clickhouse_usage_event_store.py:76-87](../../backend/src/yieldfield/infrastructure/analytics_store/clickhouse_usage_event_store.py)); `append` cross-checks each event's tenant (59-62). API-level cross-tenant 404 pins exist for jobs, findings, reconciliations, connectors.
- **AuthN**: bearer-token→tenant map; missing/blank/malformed/unknown all rejected ([auth.py:21-33](../../backend/src/yieldfield/api/v1/dependencies/auth.py)) and each case is pinned ([test_api_dependencies.py:28-49](../../backend/tests/unit/test_api_dependencies.py)) — including the earlier empty-token fail-open, now a regression pin. Tenant is never read from a request body anywhere.
- **Secrets**: Fernet encryption at rest with error messages that never carry plaintext ([credential_cipher.py](../../backend/src/yieldfield/infrastructure/security/credential_cipher.py)); connector responses expose only id/type/status ([schemas/connectors.py:16-21](../../backend/src/yieldfield/api/v1/schemas/connectors.py)); 422 responses redact submitted input ([handlers.py:65-77](../../backend/src/yieldfield/api/errors/handlers.py)); both behaviors are pinned. No log statement emits a secret (all `log.` call sites reviewed).
- **Webhooks**: signature verified before any state change; fail-closed when no secret is configured (raises, pinned at adapter and route); invalid/missing signature → 400 with nothing enqueued; job is created only for the connector row's own tenant (pinned). Stripe tolerance = 300 s.
- **Injection**: no raw SQL string composition anywhere (`text()` only in the readiness `SELECT 1`); ClickHouse uses server-side parameters; the one interpolated identifier is the constructor-controlled table name.

**Findings:**

| ID | Sev | Finding |
|---|---|---|
| SE-1 | **Important** | **Zero-decimal currencies produce silently wrong money** — [stripe_billing/mapping.py:29-30](../../backend/src/yieldfield/infrastructure/connectors/stripe_billing/mapping.py) divides every Stripe amount by 100. For JPY/KRW/etc. (zero-decimal in Stripe), stored invoice amounts are wrong by 100×, and reconciliation then emits wrong-dollar findings. The docstring names the two-decimal assumption, but the module *computes wrong numbers silently* instead of failing loudly — contrary to the project's own §7 fail-loud money principle (compare `_storable`, which raises rather than rounds). *Impact:* incorrect financial findings for any tenant billing in a zero-decimal currency. *Smallest fix:* a two-decimal currency allowlist in `_money_from_minor` that raises `ConnectorError` otherwise. *Class:* implementation issue (money correctness). |
| SE-2 | **Important** | **No rate limiting or body cap on the unauthenticated webhook surface** — `POST /webhooks/{connector_id}` reads the full body unbounded ([webhooks/router.py:59](../../backend/src/yieldfield/api/webhooks/router.py)) and there is no throttle anywhere in the app. Signature replay within the 300 s tolerance (or a provider retry storm) creates one Job + one full Stripe re-pull *each*; job rows are never pruned. Ingestion stays correct (idempotent re-pull, §8) but the ledger, the DB, and the tenant's Stripe rate limit absorb the flood. *Fix (smallest):* per-connector throttle at the route (or edge), request-size cap, and an event-id dedup ledger later. *Class:* security/reliability. |
| SE-3 | Minor | **All tokens are omnipotent** — one scope, no expiry, no rotation story; token comparison is a dict lookup (not constant-time, practically fine). Explicitly the Slice-4 OIDC seam ([auth.py:3-5](../../backend/src/yieldfield/api/v1/dependencies/auth.py)); acceptable *only* until real tenants. *Class:* documented technical debt. |
| SE-4 | Minor | **Concurrency is convergence-by-idempotency, not locking** — duplicate delivery of the same job runs `work()` twice ([run_as_job.py:66-68](../../backend/src/yieldfield/infrastructure/messaging/run_as_job.py) treats RUNNING as re-runnable); reconciliation `add` is delete-then-reinsert ([repositories.py:150-157](../../backend/src/yieldfield/infrastructure/persistence/repositories.py)) with no row lock. Two concurrent runs of the *same* reconciliation_id can interleave (last commit wins; SELECT-then-DELETE race can raise). Defensible for Slice 3 (documented §8 posture) — record it as an accepted risk with `SELECT … FOR UPDATE` on the Job row as the eventual hardening. *Class:* architecture (accepted risk). |
| SE-5 | Minor | `DISABLED` connector status is never checked at webhook ingress or `build_authenticated` ([registration.py:79-90](../../backend/src/yieldfield/infrastructure/connectors/registration.py)). Currently unreachable (no disable API), but the moment Slice 4 adds disable, webhooks keep working unless both paths gain the check. *Class:* forward-looking security gap. |
| SE-6 | Minor | `debug` and docs exposure are not forbidden in production — `FastAPI(debug=settings.debug)` ([main.py:32](../../backend/src/yieldfield/api/main.py)) would return tracebacks if misconfigured; `/api/v1/docs` is always on. Fold into the production settings validator (PR-1). *Class:* configuration hygiene. |

---

## 3. API — contract is consistent, enveloped, and drift-guarded

All 15 paths verified against the committed schema (drift gate green). Request validation is real: tz-aware windows with `end ≥ start` ([schemas/common.py:33-53](../../backend/src/yieldfield/api/v1/schemas/common.py) — matches the domain `TimeWindow` exactly, including allowing the degenerate empty window); enum-validated connector types; bounded pagination (`limit ≤ 200`) with opaque cursors that 400 on tampering, wrong prefix, or negative offset (all pinned). Every error path returns the `{error:{code,message,details}}` envelope including the 500 catch-all; money serializes as decimal strings at storage scale (pinned end-to-end). The async contract (202 `{job_id}` → `GET /jobs/{id}` → `result_ref`) is uniform across ingestion/reconciliation/webhooks. POST /reconciliations pre-generates the run id so worker redelivery converges while each POST is a new auditable run (decision C/E) — correct idempotency semantics for an append-only audit trail.

| ID | Sev | Finding |
|---|---|---|
| API-1 | **Important** | **“Window” means different things on ingest vs reconcile** — invoice ingestion filters Stripe by **`created`** ([stripe_billing/connector.py:66-75](../../backend/src/yieldfield/infrastructure/connectors/stripe_billing/connector.py)); reconciliation selects invoices by **`period_start`** ([repositories.py:133-143](../../backend/src/yieldfield/infrastructure/persistence/repositories.py)). An invoice for January created on Feb 3 (the normal case — invoices finalize after the period) is *not* pulled by an “ingest January” window, then silently missing from “reconcile January”. The E2E works only because it ingests 2008–2030. *Impact:* silent under-ingestion → missed leakage, the product's worst failure mode. *Smallest fix:* pull with a padded `created` window and filter client-side by period (plus document the semantics in `IngestionRequest`). *Class:* implementation issue. |
| API-2 | Minor | Auth appears in OpenAPI as an optional `authorization` header parameter, not a `securityScheme` — the Slice-4 generated client won't model authentication idiomatically. *Fix:* switch the dependency to `HTTPBearer(auto_error=False)` (same behavior, correct schema). *Class:* documentation/contract gap. |
| API-3 | Minor | Invalid cursors return generic `http_400` instead of a semantic code ([pagination.py:34-37](../../backend/src/yieldfield/api/v1/dependencies/pagination.py)) — the one enveloped error without a stable machine code. *Class:* consistency. |
| API-4 | Minor | List endpoints materialize the tenant's full result set then slice in memory ([reconciliations.py:74-77](../../backend/src/yieldfield/api/v1/routers/reconciliations.py) plus the same pattern for connectors/findings). Named simplification ([pagination.py:2-6](../../backend/src/yieldfield/api/v1/dependencies/pagination.py)); becomes a real cost with data volume. *Class:* documented technical debt (see PF-2). |
| API-5 | Minor | `version="0.0.0"` ([main.py:31](../../backend/src/yieldfield/api/main.py)) is baked into the committed contract — fine pre-release; needs a bump/release story before external consumers. |

---

## 4. Workers — lifecycle is exact; resilience policy is thin by design

**What holds:** `run_as_job`'s transaction choreography is precisely what an operational money ledger needs — RUNNING committed first (pollers see progress), business write + SUCCEEDED atomically, FAILED durable *after* rolling back partial writes, terminal redelivery a no-op — all six behaviors pinned ([test_run_as_job.py](../../backend/tests/unit/test_run_as_job.py)). Commit-before-enqueue closes the fast-worker race ([services.py:109-139](../../backend/src/yieldfield/api/v1/dependencies/services.py)); `task_acks_late` + `worker_prefetch_multiplier=1` + `task_reject_on_worker_lost` is the right at-least-once posture given idempotent use-cases; task names are the pinned API↔worker contract; structured logs carry tenant/job/outcome on every transition.

| ID | Sev | Finding |
|---|---|---|
| WK-1 | **Important** | **No retry ceiling and no dead-letter path** — tasks define no `max_retries`/DLQ, and with `task_reject_on_worker_lost=True` a payload that *kills the worker* (OOM on a huge window, native crash) is redelivered indefinitely: a poison-message loop that also re-marks the job RUNNING each cycle. Exception-type failures are safe (FAILED, no retry), so the loop needs a worker death — rare but catastrophic when hit. *Smallest fix:* delivery-count guard in `run_as_job` (fail the job if `self.request.delivery_info` shows redelivery of a RUNNING job) or broker-level delivery limit. *Class:* reliability. |
| WK-2 | **Important** | **Orphaned PENDING jobs have no sweeper** — enqueue-after-commit failure is documented as leaving a durable PENDING row with no worker ([services.py:116-118](../../backend/src/yieldfield/api/v1/dependencies/services.py)), and nothing ever times them out; clients poll forever. *Smallest fix:* a periodic (Celery beat) sweep marking PENDING older than N hours FAILED with a reason. *Class:* reliability/UX. |
| WK-3 | Minor | No cancellation surface (jobs cannot be revoked) and `GET /jobs` list does not exist — operators can only inspect known job ids. Fine for the slice; note for the ops story. |
| WK-4 | Minor | The production enqueue path (`send_task` → broker → worker) is exercised by no test — units fake the queue; the E2E deliberately bypasses `send_task` because Celery ignores `task_always_eager` for it ([tests/e2e/conftest.py:148-155](../../backend/tests/e2e/conftest.py)). The name contract is pinned, but the first real broker round-trip happens in deployment. *Fix:* one integration test with a real Redis container and a worker thread. *Class:* testing gap. |

---

## 5. Testing — a genuinely strong suite; gaps are specific, not systemic

**What holds:** 281 tests with the weight exactly where the money is: exhaustive `Money`/`TimeWindow`/matching units; property-grade precision pins both directions on the NUMERIC(38,12) guard; security regressions pinned *at the API level* (cross-tenant 404s on jobs/findings/reconciliations, list scoping on connectors, secret-echo redaction, webhook fail-closed both layers, empty-bearer fail-open); Docker integration for migrations, repositories, ClickHouse round-trip (including decimal precision and window-boundary exclusion), Stripe connector against stripe-mock with *real HMAC signature* verification vectors (valid/tampered/stale); an E2E that runs register → ingest (stripe-mock) → reconcile → finding lifecycle → 409 through the real API with real datastores and real worker composition roots. Fakes were made tenant-aware after that class of bug bit once — the suite learns.

Meaningful missing behavior (no percentages, per instruction):

| ID | Sev | Gap |
|---|---|---|
| TE-1 | **Important** | **Webhook → job E2E** — the highest-risk surface (unauthenticated ingress) is never exercised end-to-end: no test POSTs a genuinely-signed payload to `/api/v1/webhooks/{id}` against the real registration service + cipher + DB. Unit fakes + adapter signature vectors cover the halves; the composition (decrypt real blob → verify real signature → enqueue) is uncovered. |
| TE-2 | **Important** | **Zero-decimal / non-USD money behavior is untested** — nothing pins what happens when a Stripe payload carries `jpy` (see SE-1); mixed-currency reconciliation (documented out of scope) also has no pin proving it fails loudly rather than silently mixing. |
| TE-3 | Minor | The worker tasks' *composition* (`run_reconciliation_task` etc.) runs only in the E2E happy path; the `ingestion_enabled=false` worker-side gate (RuntimeError → FAILED job) and the foreign-connector job failure have no direct test. |
| TE-4 | Minor | `_JOB_TYPE_BY_TASK[task_name]` KeyError on an unknown task name ([services.py:132](../../backend/src/yieldfield/api/v1/dependencies/services.py)) is an unmapped 500 if a new route passes a new name without extending the map — no pin forces the map/name pairing. |
| TE-5 | Minor | Flake surface: E2E/integration rely on `wait_for_logs` string matching (already deprecation-warned) and container startup timing; no retry annotations. Observed green repeatedly, but the deprecation will eventually break collection on a testcontainers upgrade. |

---

## 6. Production readiness — the code is ahead of its runway

| ID | Sev | Finding |
|---|---|---|
| PR-1 | **Important** | **No production config validation** — `database_url`, `clickhouse_url`, `credentials_key` are `None`-able and `api_tokens` defaults to `{}` ([settings.py:53-64](../../backend/src/yieldfield/config/settings.py)); `create_app()` touches none of them, so a production boot with *no database* succeeds and every request 500s. The `is_production` property exists but nothing uses it. *Smallest fix:* a `model_validator` requiring the datastore URLs, a non-empty token map, `log_json=True`, and `debug=False` when `environment=="production"`. *Class:* production readiness. |
| PR-2 | **Important** | **`docker compose up` does not yield a working system** — the shared env block ([docker-compose.yml:63-70](../../docker-compose.yml)) omits `YIELDFIELD_API_TOKENS`, `YIELDFIELD_CREDENTIALS_KEY`, `YIELDFIELD_INGESTION_ENABLED`, `YIELDFIELD_CONNECTOR_BASE_URL` (they are documented in `.env.example` but compose never passes them through), so the containerized API 401s every request and 500s on connector registration. *Fix:* `${...}` pass-throughs in the anchor. *Class:* configuration. |
| PR-3 | **Important** | **No migration step anywhere in the runtime path** — API/worker images start their servers directly ([Dockerfile.api:24](../../infrastructure/docker/Dockerfile.api), [Dockerfile.worker:21](../../infrastructure/docker/Dockerfile.worker)); compose has no init service; `ops/README.md` names no command. A fresh stack has zero tables. *Fix:* an entrypoint or one-shot compose service running `alembic upgrade head` (+ `bootstrap_clickhouse.py`), and document it. *Class:* production readiness. |
| PR-4 | **Important** | **Observability floor is logging only** — no request/correlation-id middleware, no metrics, no tracing, no error tracker; `/ready` is the entire ops surface. For a product whose pitch is auditability, at minimum: request-id contextvar middleware (structlog is already contextvars-ready, [logging.py:33](../../backend/src/yieldfield/config/logging.py)), job duration/outcome counters, and Sentry-or-equivalent. *Class:* production readiness. |
| PR-5 | Minor | Engine lifecycle: process-cached engines are never disposed on shutdown (no lifespan hook), `/ready` builds and disposes a fresh engine per probe ([readiness.py:24-33](../../backend/src/yieldfield/api/v1/dependencies/readiness.py)) — connection churn under aggressive probe intervals; pool sizing is not configurable. |
| PR-6 | Minor | CI runs no dependency/security scanning (no pip-audit/npm-audit/dependabot config) and builds no images — the Dockerfiles are exercised by nothing. |
| PR-7 | Minor | Version-drift caveat: repo pins Python 3.12 (`backend/.python-version`, Dockerfiles, CI) but this workstation can only verify on 3.14 (OS App Control blocks uv's 3.12 shims) — local green ≠ pinned-interpreter green. CI covers 3.12, so the gap is local-only; worth knowing when debugging discrepancies. |
| PR-8 | Minor | `log_json` is a manual flag, not derived from environment — a staging deploy that forgets it ships human-format logs to the aggregator (fold into PR-1). k8s/terraform are README-only placeholders (expected at this stage; listed for completeness). |

---

## 7. Performance — nothing user-facing today; three scale cliffs to plan for

| ID | Sev | Finding |
|---|---|---|
| PF-1 | **Important** | **Reconciliation memory + query profile** — one run loads *all* window invoices and *all* window usage events into memory ([run_reconciliation.py:76-78](../../backend/src/yieldfield/application/reconciliation/run_reconciliation.py)), then issues 1 + N queries per customer for contracts/plans ([:134-140]) — for 10k customers that is ~20k queries and the full event volume in RAM. Worker-side (no request latency), but it caps tenant size hard. *Fix when needed:* batch-load contracts+plans for the window's customers (2 queries), stream usage per customer from ClickHouse. |
| PF-2 | **Important** | **Unbounded lineage arrays** — every finding stores *every* usage-event id for its metric/period ([matching.py:100-103](../../backend/src/yieldfield/domain/reconciliation/matching.py) → `ARRAY(Text)` [models.py:151-153](../../backend/src/yieldfield/infrastructure/persistence/models.py)). A metric with 1M events/period makes each finding row megabytes; reads (`selectin` on the reconciliation) drag it all in. *Fix:* cap with count+sample (lineage stays reconstructable via reconciliation window + metric), or a side table. |
| PF-3 | Minor | Stripe usage pull is meters × customers API calls ([connector.py:100-117](../../backend/src/yieldfield/infrastructure/connectors/stripe_billing/connector.py)) — hits Stripe rate limits around ~10³ customers; also lists *all* subscriptions ever (`status:"all"`, no window). |
| PF-4 | Minor | Missing indexes for the hot reconciliation reads: `invoices(tenant_id, period_start)` and `contracts(tenant_id, customer_id)` (only bare `tenant_id` indexes exist — migration 0001/0002). Cheap to add now, painful after data. |
| PF-5 | Minor | ClickHouse reads use `FINAL` ([clickhouse_usage_event_store.py:78](../../backend/src/yieldfield/infrastructure/analytics_store/clickhouse_usage_event_store.py)) — correct with ReplacingMergeTree, expensive at volume; fine until PF-1 is addressed (same milestone). |

Non-findings (checked, fine): sync `def` routes run in the threadpool (correct for the sync SQLAlchemy stack); per-request session lifecycle is clean; no N+1 in API reads (`selectin` for line items/findings is deliberate and bounded by pagination… bounded once PF-2/API-4 land).

---

## 8. Code quality & governance compliance — exemplary

Readability is a genuine strength: every module opens with a docstring that states *why it exists and which governing-doc section binds it*, and the §-references sampled all check out against `PROJECT_CONTEXT.md`/`ARCHITECTURE.md` (layer boundaries §6, money §7, tenant isolation §11, config §16, connector seam §17). Naming is domain-first and consistent; files are small and single-purpose; there is no dead code (the `ping` task is a documented smoke task); no TODO/FIXME litter (work is tracked in plans); named simplifications are documented *at the code site* rather than silently assumed — a rare discipline. The governance docs themselves are current with the implementation (ARCHITECTURE's tree matches reality; the connectors growth-axis packages are the only not-yet-real entries and are marked as such).

Minor notes: AR-1 duplication (above); `db_session` commits on read-only requests ([database.py:26](../../backend/src/yieldfield/api/v1/dependencies/database.py)) — harmless, slightly noisy; `.env.example` omits `debug`/`api_host`/`api_port`/`app_name` (defaults are sane).

---

## 9. Frontend state & deployment scaffolding (assessment, not deep audit)

**Frontend (~315 LoC):** honest Slice-4-ready scaffolding, not vaporware — React 18 + TS 5.6 + Vite 6, React Query provider in place, feature-slice structure (`connectors/dashboard/findings/reconciliation`) with barrels, design-system layer with theme provider, and the *boundary rules are enforced in CI* (ESLint cross-feature import ban, hex-color bans in ESLint+Stylelint, Prettier, tsc strict, Vitest — all green jobs). Only 2 test files / ~10 tests, appropriate to the code present. `contracts/generated/` awaits the typed client. No blockers for Slice 4; the one preparatory item is API-2 (securityScheme) so the generated client models auth.

**Deployment:** compose is well-shaped (healthchecked datastores, env anchoring, volumes) but PR-2/PR-3 currently make the promised one-command experience non-functional end-to-end; images run as root with no HEALTHCHECK (hardening later); k8s/terraform are placeholders.

---

## Consolidated findings

| ID | Severity | Category | Where |
|---|---|---|---|
| SE-1 | Important | Money correctness | `stripe_billing/mapping.py:29-30` |
| API-1 | Important | Correctness (silent under-ingestion) | `stripe_billing/connector.py:66-75` vs `repositories.py:133-143` |
| SE-2 | Important | Security/reliability | `api/webhooks/router.py` (+ no app-wide throttle) |
| WK-1 | Important | Reliability (poison loop) | `workers/celery_app.py:26-28`, `run_as_job.py` |
| WK-2 | Important | Reliability (orphan PENDING) | `services.py:116-118` |
| PR-1 | Important | Production config validation | `config/settings.py:53-64` |
| PR-2 | Important | Compose env parity | `docker-compose.yml:63-70` |
| PR-3 | Important | Migrations on boot | Dockerfiles / compose / ops README |
| PR-4 | Important | Observability | app-wide |
| PF-1 | Important | Scalability | `run_reconciliation.py:76-140` |
| PF-2 | Important | Scalability | `matching.py:100-103`, `models.py:151-153` |
| TE-1 | Important | Testing gap | webhook E2E |
| TE-2 | Important | Testing gap | non-USD money |
| I-DOC | Important (documented) | Product-scope debt | un-invoiced customers invisible (`run_reconciliation.py:9-12`), contract terms ignored (`:134-140`) |
| AR-1..3, SE-3..6, API-2..5, WK-3..4, TE-3..5, PR-5..8, PF-3..5 | Minor / Future | — | as listed above |

**Critical findings: none.**

---

## Scores

| Dimension | Score | Justification |
|---|---|---|
| **Architecture** | **9 / 10** | Textbook enforced hexagonal layering: framework-pure domain, CI-checked import contracts, seams documented where they live, zero speculative abstraction. Docked for the duplicated composition roots and import-time side effects — real but small. |
| **Security** | **7 / 10** | For the implemented threat model — tenant isolation, secret handling, webhook auth — the work is rigorous *and pinned by regression tests*, which is rarer than the controls themselves. The score reflects what is deferred, not what is broken: static omnipotent tokens, no rate limiting on an unauthenticated surface, and one silent money-correctness hazard (SE-1). |
| **Testing** | **8 / 10** | Heaviest coverage exactly on money paths; security regressions pinned at the API layer; real-container integration and a true E2E. Docked for the uncovered webhook composition, non-USD money, and the never-exercised broker path. |
| **Production readiness** | **5 / 10** | The honest laggard: no prod config validation, compose can't actually serve a request, no migrations-on-boot, observability = logs only, no scanning, no image builds in CI. All fixable in days — but today this codebase cannot be *deployed* responsibly, only *run by its developers*. |
| **Overall engineering** | **8 / 10** | Unusually high craftsmanship and discipline for the stage; the deficit is concentrated in the ops/deployment slice that hasn't been built yet, plus a short list of correctness items (SE-1, API-1) that should land before real money flows. |

---

## Recommended actions (prioritized)

**Before any real tenant / real money (days of work):**
1. SE-1 — fail loudly on non-two-decimal currencies in the Stripe mapper (+ TE-2 pins).
2. API-1 — align ingest/reconcile window semantics (padded `created` pull + client-side period filter) and document.
3. PR-1 — production settings validator (datastores, tokens, cipher key, `debug=False`, `log_json=True`).
4. PR-2 + PR-3 — compose env pass-through and an `alembic upgrade head` + ClickHouse bootstrap step; then `docker compose up` truly delivers §15.
5. TE-1 — one E2E webhook test with a real signed payload.

**Slice-4-adjacent (protects the frontend work):**
6. API-2 — expose bearer auth as an OpenAPI `securityScheme` before generating the typed client.
7. PR-4 — request-id middleware + job metrics + error tracker (small, high leverage).
8. WK-2 — PENDING-orphan sweeper; WK-1 — redelivery guard in `run_as_job`.
9. SE-2 — webhook body cap + per-connector throttle.

**Before scale (plan, don't rush):**
10. PF-1/PF-2/PF-4 — batch plan/contract loading, lineage capping, and the two composite indexes (cheap now, migration-painful later).
11. SE-3 — OIDC/token rotation via the existing `auth.py` seam; connector disable + status checks (SE-5).
12. Keyset pagination behind the existing opaque-cursor contract (API-4/PF-5 milestone).

**Project-level improvements:**
- Add CI jobs: image builds (catches Dockerfile rot), `pip-audit`/`npm audit`, and a scheduled dependency-update bot.
- Promote the two “documented simplifications” with dollar impact (un-invoiced customers, contract terms) from docstrings into tracked roadmap items with explicit triggers — they are product-correctness debts, not code debts.
- Adopt a version/release convention for the API (`0.0.0` today) before the contract has external consumers.
- Consider extracting the shared API/worker composition into one module (AR-1) when Slice 4 touches DI anyway.

*Audit produced 2026-07-02 against `ca20ea8`. No code was modified; this report is the only artifact.*
