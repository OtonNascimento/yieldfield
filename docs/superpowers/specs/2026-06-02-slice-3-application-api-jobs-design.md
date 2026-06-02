# Slice 3 Design — Application + API + Ingestion/Reconciliation Jobs

**Status:** Design — pending user review
**Date:** 2026-06-02
**Branch:** `slice-3-application-api-jobs` (HEAD at the Slice 2 tip `28d3be1`)
**Governing docs:** `docs/PROJECT_CONTEXT.md`, `docs/ARCHITECTURE.md`, `docs/IMPLEMENTATION_PROMPT.md` (§96–102)
**Predecessor:** `docs/superpowers/specs/2026-05-30-slice-2-persistence-connector-design.md`

> This document is binding only insofar as it stays consistent with `PROJECT_CONTEXT.md`,
> the single source of truth. Every component traces to a governing section (cited as §N).
> No code is written until this spec is reviewed and approved.

> **Provenance note.** A prior Slice 3 design attempt (spec + a partial Plan 3A, with two
> commits) was deliberately rolled back to the Slice 2 tip and preserved on the
> `archive/slice-3-prior-design` branch. This spec is a fresh design; it reaches similar
> conclusions in places because both derive from the same governing docs and codebase, but
> every decision below was re-examined and approved in this session.

---

## 0. Scope & non-goals

**In scope — the end-to-end "money path" walking skeleton (IMPLEMENTATION_PROMPT §96–102):**
- A **minimal persisted connector** with credentials encrypted at rest, so ingestion has a
  per-tenant source of credentials (§2).
- Application use-cases over the domain: **ingest invoices/usage events**, **run reconciliation
  for tenant+window**, **transition a finding** (review / confirm / dismiss / recover) (§4).
- A thin FastAPI adapter under `/api/v1` (§5): routers per resource, Pydantic DTOs,
  tenant/auth/pagination dependencies, the standard error envelope.
- **Signed inbound webhooks** routed by stable `connector_id` (§6).
- A **persisted Jobs model** giving a durable operational history of async work, and Celery
  **workers** that are resumable and idempotent (§7).
- Idempotent ingestion (OLTP upsert + OLAP `ReplacingMergeTree`) and idempotent reconciliation
  saves (§8).
- Emit the OpenAPI schema to `contracts/openapi/` with a CI drift guard (§10 of this doc).

**Out of scope (named, deferred to their slices / triggers):**
- Any frontend (Slice 4) — no React, no typed-client generation here.
- The probabilistic scoring engine (Slice 5) — severity stays the deterministic
  `provisional_severity` from Slice 1.
- Full connector-management platform: OAuth "Connect" flows, credential rotation, update/delete
  endpoints, multi-account per type (the `connector_id` webhook routing leaves room for this — §6).
- Real OIDC/OAuth2 SSO and RBAC (§11) — a pluggable auth seam is built; the IdP integration is later.
- Outbound alerting (Slack/email), `model-runs` and `alerts` resources, and the read-only
  `invoices` / `usage-events` / `plans` / `contracts` routers (added when Slice 4 needs them).
- Cross-run finding continuity, run/job retention & pruning, and mixed-currency reconciliation
  (named in §13 of this doc as known, deferred edges).

---

## 1. Locked decisions

Reviewed and approved in this session before writing the spec:

| # | Decision | Resolution |
|---|---|---|
| A | First-cut scope | The **end-to-end money path** (register connector → ingest → reconcile → list/transition findings → poll job), not full §10 API breadth. Read-only resource routers are deferred to Slice 4. |
| B | Connector credentials at rest | Encrypt into the OLTP `connectors` table via a `CredentialCipher` **seam** with a default **Fernet** implementation (envelope/KMS-swappable later, §17). Key from `YIELDFIELD_CREDENTIALS_KEY` (§16). Adds the `cryptography` dependency and a new `infrastructure/security/` directory (§14). |
| C | Reconciliation result model | **Auditable, append-only history.** Each run is a new immutable `Reconciliation` with its own `reconciliation_id`, `executed_at`, and `rule_version`. A retry of a run converges (idempotent on `reconciliation_id`); a fresh `POST` is a new historical record. Satisfies §7 (runs versioned/replayable), §11 (immutable audit), §12 (reproducibility). |
| D | Finding lifecycle in the API | **Explicit transitions.** Routes `review` / `confirm` / `dismiss` / `recover` each map 1:1 to a domain transition; `confirm` requires a prior `review` (the domain has no `NEW → CONFIRMED` edge). Zero domain change; faithful to the §4 findings-ledger lifecycle. |
| E | Async job status | A **persisted OLTP `jobs` table** is the authoritative status surface (not the Redis result backend). It records execution lifecycle (status, timestamps, errors) durably, beyond Redis TTLs. Redis remains the Celery broker. See §7 for the operational-vs-financial split. |
| F | Webhook routing | Routed by **stable `connector_id`** — `POST /api/v1/webhooks/{connector_id}` — resolving tenant + type via `ConnectorStore.find_by_id`. This avoids a one-connector-per-tenant assumption and supports multi-account-per-type later with no route change. The signature remains the authentication (§6). |
| G | Job result reference | The `jobs` table carries a **generic `(result_type, result_ref)` pair** (a polymorphic reference), not a reconciliation-specific FK, so future job types reference different artifacts with no schema change (§17). Both columns are null-or-both-set; resolution is the reader's job (§7). |
| H | Window semantics | **Ingest** Stripe invoices by `created`; **reconcile** by billing `period_start`. Resolves the Slice-2 tension; documented, not silently rewritten. |

---

## 2. Connector-config vertical (minimal, persisted)

Slice 1/2 built the connector **port** (`domain/billing/connector_port.py`) and the Stripe
connector **class**, but no persisted connector configuration. Ingestion needs a per-tenant
source of credentials, so Slice 3 adds a **minimal** `Connector` — not the full management
platform (§0 non-goals).

**Domain** — `domain/billing/connector.py` (beside the existing `connector_port.py`; §17
connectors live under `billing`). **Pure; holds no secrets.**
- `Connector` entity: `id: ConnectorId`, `tenant_id: TenantId`, `connector_type: ConnectorType`,
  `status: ConnectorStatus`. Frozen, slotted; `id`/`tenant_id` required (`InvalidEntityError`
  otherwise).
- `ConnectorType` enum (StrEnum): `STRIPE_BILLING` (the only member this slice — the registration
  seam, §17).
- `ConnectorStatus` enum (StrEnum): `ACTIVE`, `DISABLED`.
- `ConnectorId` added to `domain/shared/ids.py`.

### 2.1 Why a `Connector` entity but **no** domain `ConnectorRepository` port (binding rationale)

This is a deliberate asymmetry. Future maintainers should not "complete the pattern" by adding a
domain repository port for connectors — doing so would re-introduce the exact coupling this
design avoids. The reasoning, captured for posterity:

1. **The entity is a business concept; its persistence is not.** A `Connector` (a tenant has a
   billing integration of some type, in some status) is part of the ubiquitous language (§8) and
   belongs in the domain. But *how* connectors are stored — and especially the **encrypted
   credential blob** — is not a business concept. The domain must never see secrets (§11), so a
   port whose whole purpose is to move an encrypted blob in and out has no place in the pure core.
2. **No inner layer depends on it.** Domain ports exist so that domain/application code can
   depend on an abstraction instead of infrastructure (the dependency rule, §6.1). Nothing in the
   domain or in the application use-cases ever loads or stores a connector: reconciliation and
   ingestion receive an already-authenticated `ConnectorPort`, built for them by the composition
   root. A port with no inner consumer is abstraction without a beneficiary — §7's "no premature
   abstraction."
3. **The only consumers are composition roots.** Connector persistence is used by the API
   (`connectors` router, webhooks) and by workers — all of which are allowed to import
   `infrastructure` directly. They have no need to go through a domain port to reach it.
4. **Therefore the store's contract lives in infrastructure.** The persistence contract is a
   `ConnectorStore` **Protocol defined in `infrastructure/connectors/`** (not in the domain),
   satisfied structurally by `SqlAlchemyConnectorRepository`. This keeps the credential-bearing
   contract on the impure side of the boundary, where it belongs.

The test that keeps this honest: the 4th import-linter contract (`application ⊥ infrastructure`,
§14) would fail if any use-case tried to reach connector persistence — so the boundary is
machine-enforced, not just documented.

**Persistence** — `infrastructure/persistence/`:
- New `connectors` table (`models.py`): `id (pk)`, `tenant_id (idx, FK tenants.id)`,
  `connector_type`, `status`, `encrypted_credentials (LargeBinary)`, `created_at`,
  `updated_at (TIMESTAMPTZ)`.
- `SqlAlchemyConnectorRepository` with the standard `_guard` tenant check (§11). It **structurally
  satisfies** the infrastructure `ConnectorStore` Protocol (§2.1): `add`, `get`,
  `list_for_tenant`, `load_credentials`, and **`find_by_id`** (the webhook-ingress resolver, §6).
- Mappers in `mappers.py` map row ↔ `Connector`; the encrypted blob is carried separately (the
  store encrypts on `add`, the registration service decrypts on use — the domain never sees it).

**Encryption** — `infrastructure/security/credential_cipher.py` (new directory under
`infrastructure/`, justified by §11 secrets-at-rest; the only structural addition to
ARCHITECTURE.md — §14):
- `CredentialCipher` Protocol: `encrypt(secrets: Mapping[str, str]) -> bytes`,
  `decrypt(blob: bytes) -> Mapping[str, str]`.
- `FernetCredentialCipher` default impl (the `cryptography` library; new dependency). Invalid key
  or bad token raises a `CredentialCipherError` that **never includes the plaintext** (§11).
- Secrets are decrypted **only** at connector construction, never logged, never serialized to any
  DTO (§11).

**Connector factory** — `infrastructure/connectors/factory.py`:
- `build_connector(connector, *, base_url=None) -> ConnectorPort` maps `connector_type → concrete
  class` (`STRIPE_BILLING → StripeBillingConnector`) and returns an **unauthenticated** instance.
  The single place a new connector type registers (§17).

**Registration service** — `infrastructure/connectors/registration.py`:
- Defines the `ConnectorStore` Protocol (§2.1) and `ConnectorRegistrationService`:
  - `register(tenant_id, connector_type, secrets) -> Connector`: build → `authenticate()`
    (validates required creds; bad creds → `ConnectorAuthError`) → encrypt → persist.
  - `build_authenticated(tenant_id, connector_id) -> ConnectorPort`: load → decrypt → authenticate
    (for ingestion/webhooks).
- This is the composition seam the API/workers call; the **application layer never touches it**,
  keeping `application ⊥ infrastructure`.

---

## 3. Jobs model & the operational-vs-financial audit split

Yieldfield is an auditing product, so async execution gets a **durable operational ledger**,
distinct from the **financial** ledger (reconciliation runs). The two never duplicate.

**Placement (no new directory):** Jobs are an *operational* concern, kept **out of the pure
domain and out of the application use-cases**, which stay job-unaware. The `JobRow` ORM +
`SqlAlchemyJobRepository` + `JobStatus`/`JobResultType` enums live in `infrastructure/persistence/`
(an OLTP table, one metadata/migration story with the others); a small `run_as_job(...)`
orchestration wrapper lives in `infrastructure/messaging/` (ARCHITECTURE.md already assigns it
"job orchestration"). The worker — a composition root — wraps each use-case with this wrapper.

**The `jobs` table (lightweight, operational only):**

| Column | Meaning |
|---|---|
| `job_id` (pk) | The handle every async `POST` returns; uniform across job types |
| `tenant_id` (idx, FK tenants.id) | Tenant scope (§11) |
| `job_type` | `RUN_RECONCILIATION` · `INGEST_INVOICES` · `INGEST_USAGE_EVENTS` |
| `status` | `PENDING → RUNNING → SUCCEEDED \| FAILED` (operational lifecycle) |
| `created_at` / `started_at?` / `finished_at?` | Execution timeline (TIMESTAMPTZ) |
| `error?` | Failure message — **no secrets, no PII** (§11) |
| `result_type?` / `result_ref?` | Generic artifact reference (decision G); both null or both set (CHECK constraint + code guard) |
| `celery_task_id?` | Optional, for ops correlation |

`JobResultType` (StrEnum, Text column): `RECONCILIATION` is the only member this slice; future
job types add members (e.g. `MODEL_RUN`, `EXPORT`) with no schema change.

**Responsibility split (the non-duplication boundary):**

| Question it answers | Owner | Never stores |
|---|---|---|
| *Did this execution start/finish/fail, when, and why?* | **`Job`** (operational audit) | findings, totals, leakage, rule logic |
| *What did the run find — leakage total, findings, window, rule_version?* | **`Reconciliation`** (financial audit) | operational status (PENDING/RUNNING/FAILED) |
| *Live broker/queue mechanics* | **Celery/Redis** | — (just the broker; OLTP `Job` is the authoritative status surface) |

They are linked by the single generic pair: a successful `RUN_RECONCILIATION` job sets
`(result_type=RECONCILIATION, result_ref=reconciliation_id)`. Ingestion jobs leave both null
(their outcome is status + timestamps; counts go to structured logs). Nothing is stored twice.

**Interaction flow:**
- **Reconciliation:** `POST /reconciliations` creates `Job(PENDING)`, generates a
  `reconciliation_id`, enqueues `run_reconciliation(job_id, reconciliation_id)`, returns
  `202 {job_id}`. The worker: `Job → RUNNING`; runs `RunReconciliation` (which persists the
  `Reconciliation` **only on success**); success → `Job → SUCCEEDED`, sets the result pair;
  exception → `Job → FAILED` with `error`, and **no** `Reconciliation` row is written. A failed
  run thus leaves a durable `FAILED` Job and no phantom business record. `GET /jobs/{job_id}`
  returns status from OLTP; on `SUCCEEDED`, the client follows `result_ref` to
  `GET /reconciliations/{id}` for the financial result.
- **Ingestion:** identical wrapper; `result_type`/`result_ref` stay null.
- **Idempotency:** a Celery redelivery/retry reuses the same `job_id` (Job transition is
  idempotent) and the same `reconciliation_id` (idempotent save converges). A fresh `POST` is a
  new Job + new run (append-only history, decision C).

---

## 4. Application use-cases

`application/<area>/`. Each use-case is a small class whose constructor takes **domain ports**
(Protocols) and whose single public method runs one use case. Use-cases import **only** `domain`
(enforced by the 4th import contract, §14). No framework, no concrete adapter, no I/O beyond the
injected ports. **Use-cases are job-unaware** (§3).

### 4.1 Ingestion — `application/ingestion/`
- **`IngestInvoices`** — `run(tenant_id, window, connector) -> int`: `connector.pull_invoices(window)`
  → `InvoiceRepository.add` **upsert-by-id** → returns the count. Window is by Stripe `created`
  (decision H).
- **`IngestUsageEvents`** — `run(tenant_id, window, connector) -> int`:
  `connector.pull_usage_events(window)` → `UsageEventStore.append` (idempotent via
  `ReplacingMergeTree`, §8) → returns the count.
- The authenticated `ConnectorPort` is built by the composition root (registration service) and
  passed in; the use-case knows only the domain abstraction.

### 4.2 Reconciliation — `application/reconciliation/`
- **`RunReconciliation`** — `run(tenant_id, window, reconciliation_id, rule_version) ->
  Reconciliation`. Orchestration:
  1. `invoices = InvoiceRepository.list_in_window(tenant_id, window)` (by `period_start`,
     decision H).
  2. Group invoices by `customer_id`.
  3. `usage = UsageEventStore.query(tenant_id, window)`, indexed by `customer_id`.
  4. For each customer, build `plans_by_metric` from that customer's `Contract`s
     (`ContractRepository.list_for_customer` → `plan_id` → `PlanRepository.get`), so the correct
     plan is attributed per customer.
  5. For each of the customer's invoices, select that customer's usage events whose `occurred_at`
     falls within `invoice.period`, and call the pure `reconcile_customer` with a `FindingId`
     factory.
  6. Assemble `Reconciliation(id=reconciliation_id, …, executed_at=now_utc, rule_version, findings)`
     and persist via `ReconciliationRepository.add` (**idempotent save** keyed on
     `reconciliation_id`, §8).
- **Currency** is taken from the window's invoices (assumed homogeneous per tenant+window);
  mixed-currency handling is deferred (§13). An empty window yields an empty run (no findings);
  currency resolution for the empty case is a Plan 3B implementation detail.
- **Usage with no covering invoice** in the window is out of scope this slice (a dedicated
  "uninvoiced usage" rule is future work, §17 strategy seam) — a known gap, not a silent omission.

### 4.3 Findings — `application/findings/`
- **`TransitionFinding`** — `run(tenant_id, finding_id, target) -> Finding`: load via
  `FindingRepository.get` (→ `EntityNotFoundError` if absent), apply the domain transition
  (`review`/`confirm`/`dismiss`/`recover`; illegal → domain `InvalidFindingTransitionError`),
  persist via `FindingRepository.update`, return the updated finding. One DRY use-case behind the
  four explicit routes (decision D).

### 4.4 Application errors
`application/errors.py`: `EntityNotFoundError` (and reuse of the domain
`InvalidFindingTransitionError` and persistence `PersistenceError`). These map to HTTP codes in
the API error handlers; **no HTTP concerns leak into the application layer**.

---

## 5. API layer — `api/v1/`

The thin HTTP adapter (§10): validate, call a use-case, serialize. **No business logic.**
Composition (sessions, repos, cipher, registration service) happens only in `dependencies/`,
the only API code permitted to import `infrastructure`.

### 5.1 Dependencies — `api/v1/dependencies/`
- **`current_tenant`** — resolves a `TenantId` from a bearer token via the config-driven
  `api_tokens` (`token → tenant_id`) map; missing/invalid → 401 (`unauthorized`). The interface is
  shaped so an OIDC validator slots in later without touching routers (§11).
- **`db_session`** — yields a request-scoped SQLAlchemy `Session`; commits on success, rolls back
  on exception, always closes.
- **`pagination`** — parses a bounded `limit` + an opaque base64 `cursor` into an internal page
  request; **cursor-based** for `findings` and `reconciliations` (§10).

### 5.2 Routers — `api/v1/routers/` (one file per resource)

| Router | Endpoints | Notes |
|---|---|---|
| `connectors` | `POST /connectors`, `GET /connectors` | Register validates creds via `authenticate()` → 400 on bad; returns `ConnectorPublic` (id, type, status) — **never** secrets. List = status only, paginated. |
| `ingestion` | `POST /ingestion/invoices` · `POST /ingestion/usage-events` → **202** | Gated by `ingestion_enabled` (off → 403 `ingestion_disabled`). Creates `Job(PENDING)`, enqueues the matching task, returns `{job_id}`. |
| `reconciliations` | `POST /reconciliations` → **202** `{job_id}`; `GET /reconciliations/{id}`; `GET /reconciliations` (paginated, newest first) | POST creates `Job` + `reconciliation_id`, enqueues. GET returns `ReconciliationRead` (id, window, currency, executed_at, rule_version, total_leakage, finding_count). |
| `findings` | `GET /findings?reconciliation_id=` (paginated); `GET /findings/{id}`; `POST /findings/{id}/{review\|confirm\|dismiss\|recover}` | Mutations return the updated `FindingRead`; illegal transition → 409. |
| `jobs` | `GET /jobs/{job_id}` | Reads the **OLTP `Job`** (authoritative): status, timestamps, error, `result_type`/`result_ref`. The poll surface for all async ops (§10). |

All routers are tenant-scoped through `current_tenant`; no endpoint accepts a `tenant_id` in its
body or path. Webhooks are the exception to bearer auth — they resolve the tenant from
`connector_id` and authenticate by signature (§6).

### 5.3 DTOs — `api/v1/schemas/`
- Pydantic models suffixed by role (§8): `ConnectorCreate`/`ConnectorPublic`, `ReconciliationRead`,
  `FindingRead`, `IngestionRequest`, `JobStatusRead`, `PageMeta`.
- **Money** serializes as `{ "amount": "<decimal string>", "currency": "USD" }` — a **string**
  amount to preserve NUMERIC(38,12) precision across the JSON boundary (§7). No floats.
- DTOs carry no secrets and no internal lineage the user shouldn't see; findings expose
  `explanation` and dollar `amount` (§2 dollars-and-explanations).

### 5.4 Error mapping — `api/errors/handlers.py` (extend the existing envelope)
Register a typed exception → `(status, code)` map onto the existing
`{ error: { code, message, details } }` envelope:

| Exception | HTTP | `code` |
|---|---|---|
| `EntityNotFoundError` | 404 | `not_found` |
| `InvalidFindingTransitionError` | 409 | `invalid_finding_transition` |
| `ConnectorAuthError` (at registration) | 400 | `connector_auth_error` |
| `InvalidWebhookSignatureError` | 400 | `invalid_webhook_signature` |
| `IngestionDisabledError` (flag off) | 403 | `ingestion_disabled` |
| missing/invalid auth | 401 | `unauthorized` |
| `RequestValidationError` (existing) | 422 | `validation_error` |

Async/ingestion connector failures surface as a **FAILED Job** via `GET /jobs/{id}`, not as an
HTTP error on the trigger call.

---

## 6. Inbound webhooks — `api/webhooks/`

- `POST /api/v1/webhooks/{connector_id}` — routed by the **stable `connector_id`** (decision F).
  A provider cannot present our bearer token; **the signature is the authentication** (§11).
- Handler: `ConnectorStore.find_by_id(connector_id)` resolves the owning **tenant + type** from
  the opaque id (the single deliberate non-tenant-prescoped read, justified because the id *is*
  the routing key and the signature gates processing). Then `build_authenticated` → 
  `verify_webhook(payload, signature)`. Signature + 300s replay tolerance already live in the
  Stripe connector.
- On **valid** → create an ingestion `Job` + enqueue an **idempotent** re-pull of the affected
  window → **202**. On **invalid** → 400 (`invalid_webhook_signature`).
- Payload parsing is minimal this slice: verify and trigger an idempotent re-pull of the relevant
  window. Per-event-type push parsing is future work — the idempotent ingest paths (§8) make a
  re-pull safe.

---

## 7. Workers & job execution — `workers/`

- Celery tasks: `run_reconciliation`, `ingest_invoices`, `ingest_usage_events`. Each task is its
  own composition root: it builds a `Session` (and a ClickHouse client / connector via the
  registration service as needed), wraps the matching use-case in `run_as_job(...)` (§3), owns its
  transaction, and closes resources. `task_acks_late=True` and `task_reject_on_worker_lost=True`
  are already configured (§13).
- **Handle = `job_id`.** Reconciliation: the API pre-generates `reconciliation_id` and passes it
  with `job_id`, so **retries reuse both ids** and the idempotent save + Job transition converge,
  while a new `POST` yields new ids (decision C/E). Ingestion: same wrapper, `result` pair null.
- **Resumability** at this slice = retry + idempotent convergence (not checkpointed progress). A
  redelivered or retried task re-runs and converges to the same record; this is the §13 posture
  for these jobs.

---

## 8. Idempotency & resumability (§13)

| Path | Mechanism |
|---|---|
| Invoice ingestion | `InvoiceRepository.add` **upsert by `invoice.id`** (delete the existing row + its line items, then re-add, in the txn). Re-ingestion converges. |
| Usage-event ingestion | ClickHouse **`ReplacingMergeTree`** on the deterministic event id; `FINAL` reads. Re-appends collapse to one row. |
| Reconciliation run | **Idempotent save keyed on `reconciliation_id`** (delete-and-replace that run's rows in the txn). A retry converges; a new execution is a new record (decision C). |
| Job lifecycle | Transitions are idempotent on redelivery (a re-run of an already-finished `job_id` converges). |
| Webhook-triggered ingest | Enqueues the same idempotent ingest paths above. |

---

## 9. Configuration additions — `config/settings.py` (§16, fail-fast)

New typed settings (all from env, validated at boot):
- `credentials_key: str | None` — Fernet key for `FernetCredentialCipher` (decision B). Required
  only when a connector is registered/used (built lazily; fails fast there if absent).
- `api_tokens: dict[str, str]` — `token → tenant_id` map backing `current_tenant` (§5.1). Parsed
  from a JSON object in `YIELDFIELD_API_TOKENS`.
- `ingestion_enabled: bool` (default `False`) — feature flag gating the live-pull
  endpoints/tasks (DoD: risky work behind a flag).

`.env.example` updated with every new key (no values; §16). New dependency: `cryptography`.

---

## 10. OpenAPI emission — `contracts/openapi/`

- `ops/scripts/export_openapi.py` imports the app and writes `contracts/openapi/openapi.json`
  (the canonical schema, §10).
- A CI step regenerates the schema and **fails if it differs from the committed file** (drift
  guard, §10/§15). Typed-client generation stays in Slice 4.

---

## 11. Observability (§13, DoD)

- Structured `structlog` events at each use-case and job boundary: `tenant_id`, `window`, entity
  counts, `job_id`/`reconciliation_id`, outcome. **No secrets, no end-customer PII** (§11).
- The existing `/api/v1/ready` probe is extended to check Postgres / ClickHouse / Redis
  connectivity (it currently returns a static shape; the TODO is already noted in the health
  router).

---

## 12. Testing plan (test-first, §7/§15)

Money paths get the deepest coverage. Tests are written before implementation.

**Unit (`tests/unit/`, no I/O — fake ports):**
- Each use-case (`IngestInvoices`, `IngestUsageEvents`, `RunReconciliation`, `TransitionFinding`)
  against in-memory fakes.
- `RunReconciliation` orchestration: customer grouping, per-customer plan resolution,
  usage→invoice period attribution, total leakage, deterministic finding ordering, idempotent
  re-run convergence.
- `FernetCredentialCipher` round-trip + wrong-key / invalid-key failures.
- Connector factory (type→class) + registration service (`register` / `build_authenticated` /
  `find_by_id`).
- `run_as_job` wrapper: success → `SUCCEEDED` + result pair; raises → `FAILED` + `error` +
  `finished_at`.
- API via FastAPI `TestClient` over each router (401 auth, error→envelope mapping, money-string
  serialization, pagination cursors, 202 + job handle), with use-cases/registration faked.
- Settings (`credentials_key`, `api_tokens`, `ingestion_enabled`).
- Webhook handler (connector_id resolution, signature valid→202+job / invalid→400), connector
  faked.

**Integration (`tests/integration/`, Docker — reuse the Slice-2 testcontainers conftest):**
- `connectors` repo + cipher round-trip against Postgres; tenant isolation; `find_by_id`.
- `jobs` lifecycle (create/transition) + tenant isolation against Postgres.
- Idempotent invoice upsert; idempotent reconciliation save.
- ClickHouse `ReplacingMergeTree` dedup + `FINAL` reads.
- Migration `0002` applies and reverses on a disposable DB (connectors + jobs + recon columns).
- Webhook signature path end to end against stripe-mock (valid → 202, invalid → 400).

**E2E (`tests/e2e/`, one critical money path):**
- Register connector → ingest invoices+usage (stripe-mock) → run reconciliation → list findings →
  review+confirm a finding → assert recovered-dollar totals, the auditable `Reconciliation` run
  record, **and** the `SUCCEEDED` Job with `(RECONCILIATION, result_ref)`.

All Docker-backed tests carry the existing `integration` marker (skipped when Docker is absent),
keeping the unit job Docker-free (§15 CI split).

---

## 13. Migrations & data lifecycle

- **OLTP** `0002`: the `connectors` table, the `jobs` table, and the `reconciliations` columns
  `executed_at` + `rule_version`. Forward-only with a working `downgrade()` (§12).
- **OLAP**: `usage_events` engine `MergeTree → ReplacingMergeTree` (§8) in the DDL and
  `ops/scripts/bootstrap_clickhouse.py`.
- **Acknowledged future work (not built here):** cross-run finding continuity (carrying human
  decisions forward across re-runs), retention/pruning of accumulated reconciliation runs and job
  records (§12 data lifecycle), and mixed-currency reconciliation. Listed so the append-only
  growth and edges are known, not solved prematurely (§7 no premature abstraction).

---

## 14. Import boundaries & guardrails (§6.1)

- **New 4th import-linter contract** (`pyproject.toml`): forbidden — `yieldfield.application` may
  not import `yieldfield.infrastructure`. Use-cases depend on domain ports only.
- The existing three contracts stay green: domain framework-purity, inward layering
  (`api → application → domain`), domain-imports-no-outer-layer.
- The composition roots permitted to import `infrastructure`: `api/v1/dependencies/`,
  `api/webhooks/`, and `workers/`.
- The new `infrastructure/security/` directory is a **structural addition to ARCHITECTURE.md**
  (which lists `persistence`, `analytics_store`, `connectors`, `scoring_engine`, `messaging`,
  `notifications` under `infrastructure/`). It is justified by §11 (secrets at rest); the tree +
  responsibilities table get a `security/` row. This is the **only** structural change to the
  architecture doc.

---

## 15. Decomposition into implementation plans

Slice 3 is delivered as three plans, each its own writing-plans → implementation cycle, executed
in order. Each plan ends green on its own gates.

| Plan | Contents | Tested by |
|---|---|---|
| **3A — Foundations & persistence** | `cryptography` dep + 4th import contract + ARCHITECTURE `security/` edit; config additions (§9); `CredentialCipher`; `Connector` entity + `ConnectorId`; `connectors` table + repo + mappers; reconciliation audit columns; `jobs` table + repo + enums; idempotent OLTP saves (§8); ClickHouse `ReplacingMergeTree`; connector factory + registration service; migration `0002` | unit + integration |
| **3B — Application use-cases** | `application/ingestion`, `application/reconciliation` (orchestration), `application/findings` (`TransitionFinding`), `application/errors` — pure, domain-ports-only | unit (fake ports) |
| **3C — API + webhooks + workers + OpenAPI** | dependencies, routers, DTOs, error mapping, webhooks (`connector_id`), Celery tasks + `run_as_job`, OpenAPI emission + CI drift guard, `/ready` extension, observability, E2E | unit + integration + E2E |

---

## 16. Traceability

| Component | PROJECT_CONTEXT § | ARCHITECTURE directory |
|---|---|---|
| Application use-cases | §6.1 (orchestration distinct from rules) | `application/{ingestion,reconciliation,findings}/` |
| Connector config + cipher + factory + registration | §17, §11 | `domain/billing/`, `infrastructure/persistence/`, `infrastructure/security/`*, `infrastructure/connectors/` |
| Jobs model + orchestration wrapper | §13 | `infrastructure/persistence/`, `infrastructure/messaging/` |
| FastAPI routers/DTOs/deps | §10 | `api/v1/{routers,schemas,dependencies}/` |
| Tenant scoping per request | §11 | `api/v1/dependencies/` |
| Signed inbound webhooks (by connector_id) | §11 | `api/webhooks/` |
| Celery jobs (handle = job_id; OLTP status) | §13 | `workers/`, `infrastructure/messaging/` |
| OpenAPI emission + drift guard | §10, §15 | `ops/scripts/`, `contracts/openapi/` |
| Config additions (fail-fast) | §16 | `config/` |
| Tests (unit/integration/e2e) | §7, §15 | `tests/{unit,integration,e2e}/` |

\* `infrastructure/security/` is the one new directory (see §14).

---

## 17. Definition of done

Tested (money paths hardest, test-first), type-clean (`mypy --strict`), lint/format-clean
(ruff + black), all **four** import-linter contracts green, observable (structured logs;
`/ready` checks dependencies), risky work behind `ingestion_enabled`, OpenAPI emitted and
drift-checked in CI, and every component traceable to a `PROJECT_CONTEXT.md` section and an
`ARCHITECTURE.md` directory. The slice does exactly what §0 scopes — no more. Then **stop and
report**.
