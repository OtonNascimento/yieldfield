# Slice 2 — Persistence + First Connector (Stripe Billing): Design Spec

**Status:** Draft for review
**Date:** 2026-05-30
**Governs:** Slice 2 of `docs/IMPLEMENTATION_PROMPT.md`
**Traces to:** PROJECT_CONTEXT §11 (multi-tenancy), §12 (database strategy), §13 (scalability),
§16 (config), §17 (ports & adapters); ARCHITECTURE `infrastructure/persistence/`,
`infrastructure/analytics_store/`, `infrastructure/connectors/base|stripe_billing/`,
`ops/migrations/`.

> The governing documents are the single source of truth. Where this spec is silent, the
> documents win. Where this spec makes a concrete choice the documents left open, the choice
> is recorded here with its rationale and section reference.

---

## 1. Scope

**In scope**
- Domain persistence **ports** (pure Protocols) for the OLTP aggregates and the OLAP usage-event store.
- **OLTP adapter** (`infrastructure/persistence/`): SQLAlchemy models, pure mappers, tenant-scoped repositories, engine/session factory, Alembic metadata glue.
- **OLAP adapter** (`infrastructure/analytics_store/`): ClickHouse usage-event store.
- **Forward-only Postgres migrations** (`ops/migrations/`, Alembic).
- **Stripe connector**: `infrastructure/connectors/base/` (abstract base + shared utils) and
  `infrastructure/connectors/stripe_billing/` (authenticate, pull usage events, pull invoices, verify webhook).
- **Integration tests**: disposable Postgres + ClickHouse (testcontainers), Stripe via `stripe-mock`,
  deterministic webhook-signature unit test, gated live test-mode tests.

**Out of scope (deferred, with reason)**
- **Connector-credential persistence + envelope encryption (§11)** → Slice 3, where the connectors
  use-case/API lands. Slice 2's connector receives `ConnectorCredentials` at `authenticate()` time.
- **`ModelRunRepository` (§12 model-run metadata)** → Slice 5. Nothing produces a `ModelRun` until the
  scoring engine exists; building its repository now would be speculative (YAGNI; DoD "no more than scoped").
- **Application use-cases, API routes, worker wiring** → Slice 3.
- **Postgres row-level security** → documented defense-in-depth follow-up (see §8). Repository-layer
  tenant scoping is the Slice 2 enforcement mechanism.
- **Cross-store deletion/retention cascade (§12)** → later; the OLTP/OLAP boundary is established here.

---

## 2. Approach decisions

1. **Sync SQLAlchemy 2.0 + psycopg 3.** The domain `ConnectorPort`/`ScoringPort` are synchronous
   because pulls run inside synchronous Celery workers (§13). Sync persistence keeps one concurrency
   model across persistence + connectors + workers. The API tier (Slice 3) offloads repo calls to a
   threadpool. *Rejected:* async SQLAlchemy/asyncpg — forks the concurrency model against the documented
   sync-port decision.
2. **Separate ORM models + explicit mappers** (forced by §6.1). Domain entities are frozen, slotted,
   framework-pure dataclasses and must not import the ORM. `infrastructure/persistence/` owns its own
   declarative models and pure `to_domain`/`from_domain` functions. *Rejected:* imperative-mapping the
   dataclasses — couples domain objects to ORM instrumentation.
3. **Repository ports live in the domain, beside their aggregates** — mirroring the established precedent
   that `ConnectorPort` lives in `domain/billing/connector_port.py`. A Protocol referencing domain
   entities is framework-pure, so it belongs in the domain. *Rejected:* ports in `application/` — breaks
   the connector/scoring-port symmetry.

---

## 3. Source of truth (§12) — explicit

| Data | Source of truth | Store | Notes |
|---|---|---|---|
| Tenants, contracts, plans | PostgreSQL | OLTP | Configuration / relational integrity. |
| Invoices + line items | PostgreSQL | OLTP | Issued bills; transactional. |
| Reconciliations + findings | PostgreSQL | OLTP | FK integrity (finding→reconciliation→tenant); drive the lifecycle state machine; queried transactionally + tenant-scoped. |
| **Usage events** | **ClickHouse** | OLAP | High-volume, append-mostly (§12). **Postgres stores no usage events.** |
| Model-run metadata | PostgreSQL (OLTP) | — | Deferred to Slice 5 (no producer yet). |

**Cross-store consequence (intentional):** a `Finding` lives in Postgres, but its lineage
`usage_event_ids` reference rows in ClickHouse. This is why lineage is a `TEXT[]` array, **not** a
foreign key — there is no Postgres usage-event table to reference. Reconstructing full provenance
(§6.5) therefore spans both stores by design.

---

## 4. Domain persistence ports (new, pure Protocols)

All ports are `typing.Protocol`, framework-free, placed beside their aggregate (precedent: `connector_port.py`).

- `domain/billing/repositories.py`: `TenantRepository`, `ContractRepository`, `PlanRepository`, `InvoiceRepository`
- `domain/billing/usage_event_store.py`: `UsageEventStore` (separate module to honor the OLTP/OLAP split, §12)
- `domain/findings/repositories.py`: `FindingRepository`
- `domain/reconciliation/repositories.py`: `ReconciliationRepository`

**Tenant-scoping invariant (§11):** every read/write method takes `tenant_id` as a required argument.
There is **no** cross-tenant accessor in any port — isolation is encoded in the interface, not just the
implementation. Example shapes:

```text
TenantRepository.add(tenant) ; get(tenant_id) -> Tenant | None
InvoiceRepository.add(tenant_id, invoice) ; list_in_window(tenant_id, window) -> Sequence[Invoice]
FindingRepository.add(tenant_id, finding) ; get(tenant_id, finding_id) -> Finding | None ;
    list_for_reconciliation(tenant_id, reconciliation_id) -> Sequence[Finding]
ReconciliationRepository.add(tenant_id, reconciliation) ; get(tenant_id, reconciliation_id) -> Reconciliation | None
UsageEventStore.append(tenant_id, events) ; query(tenant_id, window) -> Iterable[UsageEvent]
```

---

## 5. OLTP adapter (`infrastructure/persistence/`)

- **`engine.py`** — builds the SQLAlchemy `Engine` + `sessionmaker` from `settings.database_url`,
  normalized to the `postgresql+psycopg://` driver. Raises a clear error if the URL is absent
  (fail-fast, §16).
- **`models.py`** — declarative models: `tenants`, `contracts`, `plans`, `invoices`,
  `invoice_line_items`, `reconciliations`, `findings`. Every tenant-owned table has an **indexed
  `tenant_id`** column (§12). Column types:
  - `Money` → `(amount NUMERIC(38,12), currency CHAR(3))`
  - `TimeWindow` → two `TIMESTAMPTZ` columns (`*_start`, `*_end`)
  - quantities → `NUMERIC(38,12)`
  - typed IDs (`NewType[str]`) → `TEXT`
  - finding lineage `usage_event_ids` → `TEXT[]` (events live in ClickHouse; no FK target)
  - FKs: `contracts.plan_id`→`plans`, `invoice_line_items.invoice_id`→`invoices`,
    `findings.reconciliation_id`→`reconciliations`; all tenant-owned rows carry `tenant_id`.
- **`mappers.py`** — pure `to_domain`/`from_domain` per aggregate. Reconstructs `Invoice.line_items`
  and `Reconciliation.findings` tuples; rebuilds `Money`/`TimeWindow`/`FindingLineage`.
- **`repositories.py`** — SQLAlchemy implementations of the domain ports. **Every query is
  unconditionally filtered by `tenant_id`.** Repositories accept a `Session`; transaction/commit
  boundaries are owned by the caller (application layer, Slice 3) and by tests here.
- **`metadata.py`** — exposes `Base.metadata` for Alembic ("migration glue", per ARCHITECTURE).

### 5.1 `NUMERIC(38,12)` rationale (money-path critical)

- **Exact decimal, never float (§7):** `Money`/quantities are `Decimal` and the domain rejects floats,
  so the column must be `NUMERIC`/`DECIMAL`.
- **Precision 38:** the portable "wide exact decimal" ceiling shared across engines and exactly what
  ClickHouse `Decimal128(S)` holds. Choosing 38 keeps the Postgres money/quantity columns and the
  ClickHouse `usage_events.quantity` column (`Decimal128(12)`) **precision-aligned**, so a quantity
  round-tripping OLTP↔OLAP never overflows/truncates differently. Postgres `NUMERIC` allows far more, so
  38 is a deliberate portable cap, not a Postgres limit; 38 digits is astronomically beyond any invoice.
- **Scale 12:** usage-based billing uses sub-cent unit prices (e.g. $0.0000004/token), and
  `Plan.expected_charge` computes `unit_price * quantity` with **no rounding**. 12 fractional digits
  covers micro-pricing to 10⁻¹² so we never round at the storage boundary. The same precision/scale is
  used for both money amounts and quantities — one consistent exact-decimal contract.
- **Fail-loud guard (§7):** a scale of 12 means a `Decimal` with >12 fractional digits would be
  **silently rounded on insert** — the precise silent money-path corruption §7 forbids. Therefore
  `from_domain` asserts no precision loss before writing (raises if a value's exponent exceeds the column
  scale) rather than letting Postgres round. Too-precise values fail loudly; stored values stay exact.

---

## 6. OLAP adapter (`infrastructure/analytics_store/`)

- **`clickhouse_usage_event_store.py`** — implements `UsageEventStore` via `clickhouse-connect`.
  - Table `usage_events`: columns `id String`, `tenant_id String`, `customer_id String`,
    `metric String`, `quantity Decimal128(12)`, `occurred_at DateTime64(6, 'UTC')`.
  - **Partitioned by `(tenant_id, toYYYYMM(occurred_at))`**, ordered for tenant+time scans (§12/§13).
  - `append(tenant_id, events)` and `query(tenant_id, window)` — both tenant-scoped (every query filters
    `tenant_id`, `occurred_at >= start AND occurred_at < end`, matching `TimeWindow`'s half-open semantics).
  - **`ensure_schema()`** — idempotent `CREATE TABLE IF NOT EXISTS`. ClickHouse DDL is **not**
    Alembic-managed (Alembic governs Postgres only); schema is provisioned by `ensure_schema()` plus an
    ops bootstrap script.

---

## 7. Migrations (`ops/migrations/`, Alembic)

- `alembic.ini` + `env.py` (imports `Base.metadata` from `infrastructure/persistence/metadata.py`) +
  `versions/0001_oltp_schema.py` (initial forward-only OLTP schema).
- Run via `uv run alembic -c ops/migrations/alembic.ini upgrade head`. Forward-only (§12); reviewed like
  code. CI runs migrations against the disposable Postgres before integration tests.
- ClickHouse schema is handled by `ensure_schema()` + ops bootstrap script (see §6), not Alembic.

---

## 8. Tenant scoping (§11)

- **Mechanism:** enforced at the repository layer — required `tenant_id` on every port method, and every
  SQLAlchemy/ClickHouse query unconditionally filtered by `tenant_id`. No cross-tenant accessor exists.
- **Proof:** an explicit integration test seeds two tenants and asserts tenant B reads none of tenant A's
  rows, across every repository and the usage-event store.
- **Defense-in-depth follow-up (not built now):** Postgres row-level security (a `tenant_id` GUC + RLS
  policies) is documented as a future hardening, consistent with §11 ("consider row-level security").
  Repository-layer enforcement is the Slice 2 requirement.

---

## 9. Stripe connector

- **`infrastructure/connectors/base/connector.py`** — `BaseConnector(ABC)` declaring the four
  `ConnectorPort` methods plus shared utilities: credential access that never logs secrets (§11), and a
  webhook timestamp-tolerance helper (replay-safe window, §11). Concrete connectors subclass this.
- **`infrastructure/connectors/stripe_billing/`**
  - `connector.py` — `StripeBillingConnector(BaseConnector)`, constructed **per tenant** (`tenant_id`
    stamps pulled entities). Uses the official `stripe` SDK. `authenticate()` configures the client from
    `ConnectorCredentials`; `pull_usage_events(window)` / `pull_invoices(window)` page through Stripe and
    map to domain entities; `verify_webhook(payload, signature)` uses Stripe's signed-payload verification
    with a timestamp tolerance window.
  - `mapping.py` — pure translation of Stripe invoices/usage objects → domain `Invoice`/`UsageEvent`
    (currency normalization, Stripe minor-units → `Money`, timestamps → tz-aware datetimes).
- Add `stripe` to the import-linter domain-forbidden list (defense in depth alongside `sqlalchemy`,
  `psycopg`, `clickhouse_connect`).

---

## 10. Testing (`tests/integration/`)

- Register an `integration` pytest marker (addopts already uses `--strict-markers`). A fixture skips the
  module if Docker is unavailable, so unit-only environments stay green.
- **Postgres repos** — testcontainers Postgres → `alembic upgrade head` → exercise each repository,
  including the **cross-tenant isolation** test (§8). Round-trip every aggregate (incl. `Money`
  precision, `TimeWindow`, `Invoice` line items, `Reconciliation`→`Finding` aggregation, lineage array).
- **ClickHouse store** — testcontainers ClickHouse → `ensure_schema()` → append/query, tenant scoping,
  half-open window boundary, `Decimal128(12)` quantity round-trip.
- **Stripe connector** — against `stripe/stripe-mock` (testcontainers) for `authenticate`/pull/mapping
  wiring. **Webhook signature verification is a deterministic unit test** (locally-signed payload passes;
  tampered/expired fails) with no network. Live test-mode tests are gated behind a `STRIPE_TEST_SECRET_KEY`
  env var and skipped when absent (no secrets committed; CI passes without credentials).

---

## 11. Config / deps / guards

- **Runtime deps:** `sqlalchemy>=2.0`, `psycopg[binary]>=3.2`, `alembic>=1.14`, `clickhouse-connect>=0.8`,
  `stripe>=11`.
- **Dev dep:** `testcontainers>=4`.
- **Settings (§16):** `database_url`/`clickhouse_url` stay typed-optional but the engine/store factories
  fail fast with a clear error if absent when constructed.
- **mypy:** narrow `ignore_missing_imports` overrides only where stubs are missing (e.g.
  `clickhouse_connect`, `testcontainers`); do not weaken strictness elsewhere.
- **import-linter:** add `stripe` to the domain `forbidden_modules` list.
- **CI:** add an integration step running the Docker-backed tests (GitHub Actions ubuntu provides Docker)
  and `alembic upgrade head` against the disposable Postgres.

---

## 12. Workflow

1. Fast-forward `main` → `slice-0-scaffold` HEAD (Slices 0+1 land on trunk; main is cleanly 2 commits behind).
2. Branch `slice-2-persistence-connector` off `main`.
3. Conventional commits, each tracing to §11/§12/§17 and the relevant ARCHITECTURE directory.
4. Local only — no git remote configured, so no PR push. (Re-confirm if a remote is added.)

---

## 13. Definition of done (this slice)

Tested (money paths hardest, incl. cross-tenant isolation + decimal precision), type-clean (mypy strict),
lint-clean (Ruff/Black), import-boundaries green (incl. new `stripe` guard), migrations apply forward on a
disposable DB, traceable to PROJECT_CONTEXT §11/§12/§17 and ARCHITECTURE directories. Does exactly what is
scoped — no more.
