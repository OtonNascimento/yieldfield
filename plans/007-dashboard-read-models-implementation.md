# Plan 007: Implement the dashboard read models (tenant-wide findings listing + recovery summary)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat e5abfbc..HEAD -- backend/src/yieldfield/domain/findings backend/src/yieldfield/infrastructure/persistence backend/src/yieldfield/api/v1/routers/findings.py backend/src/yieldfield/api/v1/schemas/findings.py ops/migrations contracts/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED — extends the public API surface (contract + generated client
  regenerate), adds a migration, and changes the ordering of an existing
  listing. All decisions were settled in an approved design spec.
- **Depends on**: none outstanding (plans 001–006 are merged on this branch;
  the governing spec is committed in-repo)
- **Category**: direction
- **Planned at**: commit `e5abfbc`, 2026-07-09
- **Amended**: 2026-07-09 (v2), after the executor's STOP report. Two changes:
  (1) `backend/tests/unit/test_transition_finding.py` added to scope — its
  `FakeFindingRepo` (lines 38–54) structurally implements the
  `FindingRepository` Protocol and is passed to `TransitionFinding` at four
  call sites; extending the port makes those fail `mypy --strict`
  (verified A/B by the executor: baseline clean → 4 errors after the Step-2
  port extension). The fix is mechanical: two inert stub methods on the fake.
  (2) Step 4's query-model mechanism changed from `Depends()` to `Query()` —
  a pydantic `ValidationError` raised while FastAPI instantiates a `Depends()`
  class dependency is not converted to `RequestValidationError`, so naive-tz /
  mis-ordered bounds could surface as 500 instead of the required 422
  `validation_error` envelope. `Annotated[Model, Query()]` (FastAPI ≥0.115
  query-parameter models; installed 0.136.3) routes through the standard
  validation path. Neither change touches the spec's decided shapes.

## Why this matters

Slice 4's dashboard ("recovered dollars" — the number the product is named
for) and the findings worklist ("all confirmed findings awaiting recovery")
cannot be built against today's API: `GET /api/v1/findings` requires a
`reconciliation_id` and supports no filters, and no summary endpoint exists
anywhere in the contract. The design was settled in
`docs/superpowers/specs/2026-07-09-dashboard-read-models-design.md` (committed
on this branch) and its four §6 open questions were **answered by the
maintainer on 2026-07-09 — all recommendations approved as-is** (recorded in
`plans/README.md`, "Maintainer decisions"). This plan implements exactly that
spec: nothing here is a new decision.

## Read this first

Read the spec in full before writing any code:
`docs/superpowers/specs/2026-07-09-dashboard-read-models-design.md`.
It is the authority for every shape below; this plan adds execution order,
repo conventions, and verification. Where this plan and the spec disagree,
STOP and report. The approved decisions you are bound by:

- (a) NO transition timestamps in this implementation — time filters bound the
  parent reconciliation's `executed_at` only.
- (b) Severity ordering by **stable rank** via a SQL `CASE` generated from the
  domain's `_SEVERITY_RANK`, with a test importing the domain map.
- (c) The summary lives at `GET /api/v1/findings/summary`, registered
  **before** `GET /findings/{finding_id}`.
- (d) Strictly per-currency totals; no conversion, no primary-currency flag.

## Current state (verified at `e5abfbc`)

- `backend/src/yieldfield/domain/findings/repositories.py:14-20` — the port:

```python
@runtime_checkable
class FindingRepository(Protocol):
    def get(self, tenant_id: TenantId, finding_id: FindingId) -> Finding | None: ...
    def list_for_reconciliation(
        self, tenant_id: TenantId, reconciliation_id: ReconciliationId
    ) -> Sequence[Finding]: ...
    def update(self, tenant_id: TenantId, finding: Finding) -> None: ...
```

- `backend/src/yieldfield/infrastructure/persistence/repositories.py:185-208`
  — `SqlAlchemyFindingRepository.list_for_reconciliation` filters
  `tenant_id` + `reconciliation_id`, `ORDER BY FindingRow.id`.
- `backend/src/yieldfield/api/v1/routers/findings.py:28-40` — `list_findings`
  takes `reconciliation_id: Annotated[str, Query()]` (required), calls
  `list_for_reconciliation`, paginates via `paginate(rows, page)`;
  `GET /{finding_id}` is declared at line 43; the four lifecycle POST routes
  follow.
- `backend/src/yieldfield/api/v1/schemas/findings.py` — `FindingRead`
  (with `from_finding` classmethod) and `FindingPage` only.
- `backend/src/yieldfield/api/v1/schemas/common.py:13-21` — `MoneyRead`
  (decimal-string amount, `from_money`); `:33-53` — `WindowParam` shows the
  validator register for tz-aware datetimes (422 at the boundary).
- `backend/src/yieldfield/domain/findings/severity.py:26-32` —
  `_SEVERITY_RANK: dict[Severity, int]` (good=0 … critical=4).
- `backend/src/yieldfield/infrastructure/persistence/models.py` — `FindingRow`
  has `tenant_id` (FK, `index=True`) and `reconciliation_id` (FK, `index=True`),
  NO `__table_args__`; `ReconciliationRow.executed_at` exists (server default
  now()). Money columns are `NUMERIC(38,12)` + `String(3)` currency.
- `ops/migrations/versions/0004_reconciliation_read_indexes.py` — the exemplar
  migration for 0005 (composite index, forward-only, working downgrade); its
  ORM parity pattern lives in `models.py` `__table_args__` on
  `InvoiceRow`/`ContractRow` and is pinned by
  `backend/tests/unit/test_persistence_models.py` (`_index_columns` helper).
- `backend/tests/unit/test_findings_router.py` — the fake-repo test register:
  `FakeFindingRepo` (tenant-aware fakes), `_app(repo)` via
  `dependency_overrides`, `AUTH` header helper. Line 86-90:
  `test_list_requires_the_reconciliation_id_filter` asserts bare
  `GET /findings` → 422 — this pin is **deliberately inverted** by this plan.
- `backend/tests/integration/test_oltp_repositories.py` — read-predicate
  exemplars from plan 001 (`test_list_in_window_selects_by_period_start_within_window`,
  `_window`/`_invoice`/`_contract` helpers, `session` fixture that rolls back —
  tests flush, never commit).
- `contracts/openapi/openapi.json` — drift-gated (backend exporter) and the
  generated client `contracts/generated/typescript/api.d.ts` is drift-gated in
  the CI frontend job (`npm run generate:api` + `git diff --exit-code`).
- Conventions: comments/docstrings cite spec sections; conventional commits
  with scope; infrastructure may import domain (never the reverse —
  `lint-imports` enforces).

## Commands you will need

Backend from `backend/`, frontend from `frontend/`. Machine note: set
`$env:UV_PYTHON='3.14'` in EVERY PowerShell invocation that calls uv (OS
policy blocks the pinned 3.12 locally; see `ops/README.md`, "Local-dev note").
Docker Desktop must be running for integration/E2E tests.

| Purpose | Command | Expected |
|---|---|---|
| Router tests | `uv run pytest tests/unit/test_findings_router.py -q` | all pass |
| Repo integration tests | `uv run pytest tests/integration/test_oltp_repositories.py -q` | all pass |
| Migration test | `uv run pytest tests/integration/test_migrations.py -q` | all pass |
| Full backend suite | `uv run pytest -q` | all pass (1 pre-existing skip) |
| Types / lint / format / boundaries | `uv run mypy src tests` / `uv run ruff check .` / `uv run black --check .` / `uv run lint-imports` | all clean |
| Regenerate contract | `uv run python ../ops/scripts/export_openapi.py` | writes contracts/openapi/openapi.json |
| Contract drift | `uv run python ../ops/scripts/export_openapi.py --check` | `up to date` |
| Regenerate client | `npm run generate:api` (from frontend/) | rewrites contracts/generated/typescript/api.d.ts |
| Client drift | `git diff --exit-code -- ../contracts/generated` (from frontend/) | exit 0 after regeneration |
| Frontend gates | `npm run typecheck` / `lint` / `lint:css` / `format:check` / `test` / `build` | all clean |

## Scope

**In scope** (the only files you should modify/create):

- `backend/src/yieldfield/domain/findings/repositories.py` (extend the port)
- `backend/src/yieldfield/domain/findings/rollup.py` (create `FindingRollup`)
- `backend/src/yieldfield/infrastructure/persistence/repositories.py`
  (implement `list_for_tenant` + `summarize_for_tenant`)
- `backend/src/yieldfield/infrastructure/persistence/models.py`
  (`FindingRow.__table_args__` index parity)
- `backend/src/yieldfield/api/v1/routers/findings.py`
- `backend/src/yieldfield/api/v1/schemas/findings.py` (new DTOs)
- `ops/migrations/versions/0005_findings_worklist_index.py` (create)
- `contracts/openapi/openapi.json` (regenerated, never hand-edited)
- `contracts/generated/typescript/api.d.ts` (regenerated, never hand-edited)
- `docs/superpowers/specs/2026-07-09-dashboard-read-models-design.md`
  (Status line stamp ONLY: `Design — pending maintainer review …` →
  `Approved 2026-07-09 — implemented by plans/007`)
- Tests: `backend/tests/unit/test_findings_router.py`,
  `backend/tests/unit/test_persistence_models.py`,
  `backend/tests/unit/test_transition_finding.py` (v2: extend its
  `FakeFindingRepo` with the two new port methods as inert stubs — see Step 2),
  `backend/tests/integration/test_oltp_repositories.py`,
  `backend/tests/integration/test_migrations.py`

**Out of scope** (do NOT touch):

- Keyset pagination internals (`pagination.py`) — decision G keeps the opaque
  offset cursor; the repository DOES do SQL-side WHERE/ORDER BY.
- Any transition-timestamp schema (decision (a) deferred it).
- The matcher, `Money`, reconciliation use-case, lifecycle POST routes,
  webhooks/workers, frontend feature code (Slice 4 consumes this later).
- Any cached read model — direct SQL aggregate only (decision E).

## Git workflow

- Branch: `advisor/007-dashboard-read-models`.
- One commit, e.g. `feat(api): tenant-wide findings listing + per-currency recovery summary (spec 2026-07-09)`.
- Stage files explicitly by path (never `git add -A` / `git add .`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: RED — router tests for the new surface

Extend `backend/tests/unit/test_findings_router.py` (reuse `FakeFindingRepo`,
`_app`, `AUTH`; extend the fake with `list_for_tenant` and
`summarize_for_tenant` mirroring the real signatures — tenant-aware like the
existing fake methods). Write these tests FIRST and confirm they fail:

1. **Invert the 422 pin**: replace
   `test_list_requires_the_reconciliation_id_filter` with
   `test_bare_list_is_the_tenant_wide_listing` — bare `GET /findings` → 200,
   fake receives `reconciliation_id=None` and no filters.
2. Filter forwarding: `?status=confirmed&severity=high&customer_id=cus_1&leakage_type=unbilled_usage`
   → each argument arrives at the fake exactly as typed enums/str.
3. Invalid enum value (`?status=bogus`) → 422 `validation_error` envelope.
4. Naive `executed_after` → 422; `executed_before < executed_after` → 422
   (tz-aware values, wrong order).
5. `GET /findings/summary` on a fake returning rollups in two currencies →
   response has two `currencies` blocks; each block's `by_status` carries ALL
   five statuses (zero-filled, amount `"0"`); `open.total` equals
   new+reviewed+confirmed computed server-side; empty repo → `currencies: []`.
6. Route-order pin: `GET /findings/summary` must NOT be handled by
   `GET /findings/{finding_id}` (assert it does not 404-as-finding; with the
   fake returning no findings it must still 200 with the summary shape).
7. Both new surfaces are 401 without `AUTH`.

**Verify**: `uv run pytest tests/unit/test_findings_router.py -q` → the new
tests FAIL (routes/params don't exist yet); every pre-existing test except the
deliberately replaced 422 pin still passes.

### Step 2: Domain additions (pure)

- Create `backend/src/yieldfield/domain/findings/rollup.py`:

```python
"""FindingRollup — a read model of the findings ledger (§13): one aggregate
cell per (status, leakage_type, currency). Pure domain value; built by the
repository, folded into DTOs at the API boundary."""

from __future__ import annotations

from dataclasses import dataclass

from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.shared.money import Money


@dataclass(frozen=True, slots=True)
class FindingRollup:
    status: RecoveryStatus
    leakage_type: LeakageType
    total: Money
    count: int
```

- Extend the port in `domain/findings/repositories.py` with the two methods,
  signatures exactly as the spec §3.4 and §4.3 define (`list_for_tenant` with
  the seven keyword-only optional filters; `summarize_for_tenant` with the two
  optional datetime bounds returning `Sequence[FindingRollup]`).
- (v2) In `backend/tests/unit/test_transition_finding.py`, extend
  `FakeFindingRepo` with the two new methods as inert stubs mirroring the port
  signatures (return `[]`), so the fake keeps satisfying the widened Protocol
  under `mypy --strict`. The stubs are deliberately dead for the transition
  tests — do not add behavior or new tests there.

**Verify**: `uv run lint-imports` → 4 contracts kept (the new module imports
domain only). `uv run mypy src` will flag the unimplemented protocol on the
SQL repository — expected until Step 3; run `mypy` fully only after Step 3.

### Step 3: Persistence — filtered listing, aggregate, index parity

In `infrastructure/persistence/repositories.py`:

- **Severity rank CASE, derived not hardcoded** (decision b):

```python
from sqlalchemy import case
from yieldfield.domain.findings.severity import _SEVERITY_RANK

_SEVERITY_RANK_SQL = case(
    {severity.value: rank for severity, rank in _SEVERITY_RANK.items()},
    value=FindingRow.severity,
)
```

- `list_for_tenant`: build the SELECT with the unconditional tenant predicate,
  each optional predicate appended only when non-None, a JOIN to
  `ReconciliationRow` ONLY when a time bound is set
  (`executed_at >= after` / `< before`), ordered
  `_SEVERITY_RANK_SQL.desc(), FindingRow.amount_amount.desc(), FindingRow.id.asc()`.
  Map rows via the existing `mappers.to_finding`.
- `summarize_for_tenant`: one aggregate —
  `select(FindingRow.status, FindingRow.leakage_type, FindingRow.amount_currency,
  func.sum(FindingRow.amount_amount), func.count())` with the same
  tenant predicate/JOIN pattern, `GROUP BY` status, leakage_type,
  amount_currency. Build each `FindingRollup` with
  `Money.of(str(total), currency)` (SUM over NUMERIC returns `Decimal` —
  keep it exact, never float).

In `models.py`, add ORM parity for the new index (mirror `InvoiceRow`'s
pattern and comment register):

```python
class FindingRow(Base):
    __tablename__ = "findings"
    # Worklist read path: findings are fetched per (tenant, status).
    # Created by migration 0005; the unit parity test keeps both in sync.
    __table_args__ = (Index("ix_findings_tenant_status", "tenant_id", "status"),)
```

Create `ops/migrations/versions/0005_findings_worklist_index.py` modeled
verbatim on `0004_reconciliation_read_indexes.py`: revision
`0005_findings_worklist_index`, `down_revision = "0004_reconciliation_read_indexes"`,
upgrade creates `ix_findings_tenant_status` on `findings (tenant_id, status)`,
downgrade drops it.

Add pins:

- `backend/tests/unit/test_persistence_models.py`: a parity test using the
  existing `_index_columns` helper —
  `_index_columns("findings", "ix_findings_tenant_status") == ["tenant_id", "status"]`.
- `backend/tests/integration/test_migrations.py`: extend the head assertions
  with the new index (and its absence after downgrade to `0001_oltp_schema`),
  following the 0004 lines already there.
- `backend/tests/integration/test_oltp_repositories.py`: integration tests per
  spec §8 — `list_for_tenant` tenant isolation + each predicate + ordering
  (expected order derived from `_SEVERITY_RANK`, not hardcoded);
  `summarize_for_tenant` correct sums/counts per cell, tenant isolation, a
  **multi-currency fixture proving totals never merge across currencies**, and
  `executed_at` window bounds (seed two reconciliations with different
  `executed_at`). Reuse plan-001's helper style; remember: contracts→plans FK
  needs `session.flush()` between parents and children, and findings rows are
  persisted via `SqlAlchemyReconciliationRepository.add` (see
  `test_reconciliation_persists_findings_and_reads_back` in the same file).

**Verify**: `uv run pytest tests/integration/test_oltp_repositories.py tests/integration/test_migrations.py tests/unit/test_persistence_models.py -q`
→ all pass. `uv run mypy src tests` → clean.

### Step 4: API — DTOs and router (GREEN for Step 1)

In `schemas/findings.py`, add the spec §4.2 DTOs verbatim (`StatusBucket`,
`CurrencySummary`, `FindingSummaryRead`) plus a folding classmethod
`FindingSummaryRead.from_rollups(rollups: Sequence[FindingRollup])` (the
`from_finding` register): group by currency; zero-fill all five statuses with
`MoneyRead(amount="0", currency=...)`; compute `open` = new+reviewed+confirmed
over `Money` values server-side; `by_leakage_type` sparse.

In `routers/findings.py`:

- Declare `GET /summary` **before** `GET /{finding_id}` (decision c).
- `list_findings`: `reconciliation_id` becomes `str | None = None`; add
  optional typed query params `status: RecoveryStatus | None`,
  `leakage_type: LeakageType | None`, `severity: Severity | None`,
  `customer_id: str | None`, and the two datetime bounds. For the bounds'
  validation (tz-aware, ordered), use a small Pydantic query-parameter model
  (`Annotated[FindingListWindow, Query()]` — v2: NOT `Depends()`, whose class
  instantiation can leak a raw pydantic `ValidationError` as a 500) with the
  `WindowParam` validator register (`schemas/common.py:39-50`) so violations
  surface as the standard 422 `validation_error` envelope — do NOT hand-raise
  HTTPExceptions.
- Both routes call the new repo methods; the listing keeps
  `paginate(rows, page)` (decision G).

**Verify**: `uv run pytest tests/unit/test_findings_router.py -q` → ALL pass,
including every Step-1 test.

### Step 5: Contract + generated client regeneration

1. From `backend/`: `uv run python ../ops/scripts/export_openapi.py` then
   `--check` → up to date.
2. From `frontend/`: `npm run generate:api` then
   `git diff -- ../contracts/generated` shows the regenerated types (the new
   summary path; `reconciliation_id` no longer required).
3. `uv run pytest tests/unit/test_openapi_contract.py -q` → passes (the drift
   pin compares committed schema to the app).

**Verify**: all three above, plus frontend `npm run typecheck` → exit 0 (the
shared type re-export still resolves).

### Step 6: Spec stamp + full gates

- Edit ONLY the Status line of
  `docs/superpowers/specs/2026-07-09-dashboard-read-models-design.md` to:
  `**Status:** Approved 2026-07-09 (maintainer accepted §6 recommendations as-is) — implemented by plans/007`.
- Full gates, both stacks:
  backend `uv run pytest -q` (expect the pre-existing single skip), `mypy`,
  `ruff`, `black --check`, `lint-imports`, contract `--check`;
  frontend `typecheck`, `lint`, `lint:css`, `format:check`, `test`, `build`,
  and the client-drift pair.

**Verify**: everything green; `git status` shows only in-scope files.

## Test plan

Enumerated inline in Steps 1 and 3 (they mirror the spec's §8 inventory:
router pins including the inverted 422 and route-order pin; repository
predicate/ordering/aggregation integration tests with the multi-currency
fixture; index parity + migration head/downgrade assertions; contract drift).
Patterns to copy: `test_findings_router.py` fakes, plan-001's predicate tests
in `test_oltp_repositories.py`, `test_persistence_models.py::_index_columns`,
the 0004 assertions in `test_migrations.py`.

## Done criteria

- [ ] Bare `GET /findings` (authed) returns 200; the old 422 pin is replaced,
      not merely deleted
- [ ] `GET /findings/summary` exists, registered before `/{finding_id}`, and
      returns zero-filled per-currency blocks with a server-computed `open`
- [ ] `grep -n "ix_findings_tenant_status" ops/migrations/versions/0005_findings_worklist_index.py backend/src/yieldfield/infrastructure/persistence/models.py`
      → one hit in each
- [ ] `uv run pytest -q` exits 0 (1 pre-existing skip); count strictly greater
      than 324 (new tests landed)
- [ ] mypy / ruff / black / lint-imports all exit 0; OpenAPI `--check` clean;
      `npm run generate:api` + `git diff --exit-code -- ../contracts/generated`
      clean; all six frontend gates exit 0
- [ ] The spec's Status line reads Approved/implemented
- [ ] `git status` shows no modified files outside the in-scope list
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The spec and this plan disagree anywhere — the spec wins; report the
  discrepancy instead of choosing.
- `case({...}, value=FindingRow.severity)` hits a SQLAlchemy/mypy typing wall
  you cannot resolve with a targeted annotation — report rather than switching
  to a hardcoded CASE (decision b forbids hardcoding the rank).
- OpenAPI schema generation of `dict[RecoveryStatus, StatusBucket]` produces a
  shape the generated TypeScript client cannot express (check the regenerated
  `api.d.ts` for the summary schema) — report with the generated excerpt; the
  fallback (explicit five-field model instead of a dict) changes the spec's
  §4.2 and needs maintainer sign-off.
- Any pre-existing test other than `test_list_requires_the_reconciliation_id_filter`
  fails and the fix isn't an obvious seed alignment.
- You find yourself touching pagination internals, transition timestamps, or
  any Out-of-scope file.

## Maintenance notes

- This endpoint is where offset cursors will first hurt at scale (audit
  API-4); the ordering key (severity rank, amount, id) is deliberately
  keyset-ready — the later keyset migration changes `pagination.py` and the
  repo LIMIT/OFFSET pushdown, not the wire contract.
- The summary's at-scale evolution is a cached read model invalidated on
  finding transition + reconciliation save (spec decision E) — contract
  unchanged when it lands.
- Reviewer focus: the unconditional tenant predicate in BOTH new SQL paths;
  no cross-currency addition anywhere (grep for `Money.of` folding); the
  route-order pin; and that the rank CASE is derived from `_SEVERITY_RANK`.
- Slice 4 consumes this via TanStack Query: transitions must invalidate both
  the list and summary keys (spec §5.2) — frontend work, out of scope here.
