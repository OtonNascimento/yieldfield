# Plan 001: Pin the money-path read predicates with integration tests and honest unit fakes

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 231534d..HEAD -- backend/tests/integration/test_oltp_repositories.py backend/tests/unit/test_run_reconciliation.py backend/src/yieldfield/infrastructure/persistence/repositories.py`
> If any of these changed since this plan was written, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch,
> treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW (additive tests + fake tightening only; no production code changes)
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `231534d`, 2026-07-07

## Why this matters

The reconciliation use-case is tested through unit fakes whose read methods ignore
the WHERE clauses the real SQL repositories enforce: the fake invoice repo returns
*every* invoice regardless of tenant or window, and the fake usage store returns
*every* event. Meanwhile no integration test ever calls
`SqlAlchemyInvoiceRepository.list_in_window` or exercises
`SqlAlchemyContractRepository.list_for_customer`'s tenant scoping. A regression that
weakened either predicate — leaking another tenant's invoices or out-of-window rows
into a reconciliation — would produce wrong dollar findings while the entire suite
stays green. This plan pins the real predicates at the integration layer and makes
the unit fakes model the same contract, which is also a prerequisite for Plan 002
(a behavior change to usage loading that is only testable once the fakes respect
windows).

## Current state

Relevant files:

- `backend/src/yieldfield/infrastructure/persistence/repositories.py` — the real
  SQL repositories (read-only for this plan; the predicates being pinned).
- `backend/tests/integration/test_oltp_repositories.py` — integration round-trip
  tests over a migrated disposable Postgres (the file to extend).
- `backend/tests/unit/test_run_reconciliation.py` — unit fakes to tighten
  (lines 103–139).
- `backend/tests/integration/conftest.py` — provides the `session` fixture
  (a `Session` over a migrated engine; **rolls back after each test**, so tests
  `session.flush()` and never commit).

The real predicates (repositories.py, verbatim at `231534d`):

```python
# repositories.py:104-110
def list_for_customer(self, tenant_id: TenantId, customer_id: str) -> Sequence[Contract]:
    rows = self._session.scalars(
        select(ContractRow)
        .where(ContractRow.tenant_id == str(tenant_id), ContractRow.customer_id == customer_id)
        .order_by(ContractRow.id)
    ).all()
    return [mappers.to_contract(r) for r in rows]

# repositories.py:134-144
def list_in_window(self, tenant_id: TenantId, window: TimeWindow) -> Sequence[Invoice]:
    rows = self._session.scalars(
        select(InvoiceRow)
        .where(
            InvoiceRow.tenant_id == str(tenant_id),
            InvoiceRow.period_start >= window.start,
            InvoiceRow.period_start < window.end,
        )
        .order_by(InvoiceRow.id)
    ).all()
    return [mappers.to_invoice(r) for r in rows]
```

Note the invoice predicate selects by **`period_start` inside the half-open window**
— an invoice whose period *overlaps* the window but starts before it is deliberately
NOT selected (each invoice reconciles in exactly one window: the one containing its
`period_start`, provided windows tile contiguously). Your new test pins this
partitioning semantic; do not "fix" it — Plan 002 documents it.

The dishonest fakes (test_run_reconciliation.py, verbatim at `231534d`):

```python
# test_run_reconciliation.py:113-114
def list_in_window(self, tenant_id: TenantId, window: TimeWindow) -> Sequence[Invoice]:
    return list(self._invoices)

# test_run_reconciliation.py:124-125
def query(self, tenant_id: TenantId, window: TimeWindow) -> Sequence[UsageEvent]:
    return list(self._events)

# test_run_reconciliation.py:138-139
def list_for_customer(self, tenant_id: TenantId, customer_id: str) -> Sequence[Contract]:
    return [c for c in self._contracts if c.customer_id == customer_id]
```

Domain constructors you will need (all frozen dataclasses):

- `Contract(id=ContractId(...), tenant_id=TenantId(...), customer_id="cus_1",
  plan_id=PlanId(...), term=TimeWindow(...))` — note `term` is a `TimeWindow`,
  not two datetimes (`backend/src/yieldfield/domain/billing/contract.py:13-19`).
- `TimeWindow(start, end)` — timezone-aware, half-open `[start, end)`
  (`backend/src/yieldfield/domain/shared/time_window.py`); has
  `.contains(moment)` and `.overlaps(other)`.
- `Invoice`/`InvoiceLineItem` — copy the construction pattern from
  `test_oltp_repositories.py:64-84` (existing exemplar in the same file).

Conventions to match: the integration file already defines helpers `_tenant`,
`_plan` and a module `_WINDOW = TimeWindow(datetime(2026, 1, 1, tzinfo=UTC),
datetime(2026, 2, 1, tzinfo=UTC))` — reuse them; add helpers in the same style.
Docstring register is one-line, spec-section-citing (e.g. "(§11)").

**FK gotcha (load-bearing)**: `contracts.plan_id` has a foreign key onto
`plans.id`, and the ORM has NO relationship ordering plans before contracts in the
unit of work — you MUST `session.flush()` after adding plans and before adding
contracts, or the insert order is undefined. See the comment at
`backend/src/yieldfield/infrastructure/persistence/models.py:42-45` and the same
pattern with an explanatory comment in `backend/tests/e2e/test_money_path.py:101-103`.
Tenants are ordered automatically before their children (relationships exist for
that), but flushing after tenants too is harmless and matches the exemplar tests.

## Commands you will need

All backend commands run from `backend/` (the uv project root).

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `uv run pytest -m "not integration" -q` | all pass |
| Integration tests (needs Docker running) | `uv run pytest -m integration -q` | all pass |
| One file | `uv run pytest tests/integration/test_oltp_repositories.py -q` | all pass |
| Types | `uv run mypy src tests` | `Success: no issues` |
| Lint | `uv run ruff check .` | `All checks passed!` |
| Format | `uv run black --check .` | `unchanged` |
| Import boundaries | `uv run lint-imports` | `Contracts: 4 kept, 0 broken` |

Machine note: if `uv` errors while trying to provision Python 3.12 (an OS
Application Control policy on this workstation blocks uv-managed interpreters),
set `UV_PYTHON` to an allowed interpreter first — PowerShell:
`$env:UV_PYTHON='3.14'`. See `ops/README.md`, "Local-dev note".

## Scope

**In scope** (the only files you should modify):

- `backend/tests/integration/test_oltp_repositories.py`
- `backend/tests/unit/test_run_reconciliation.py`

**Out of scope** (do NOT touch):

- `backend/src/**` — no production code changes in this plan. In particular do
  NOT change `list_in_window`'s predicate; the straddling-invoice exclusion is a
  documented partitioning semantic (see Plan 002), not a bug to fix here.
- `backend/tests/e2e/**` and other test files.

## Git workflow

- Branch: `advisor/001-money-path-read-predicate-tests` (branched from the current
  working branch).
- One commit, conventional style with scope, e.g.
  `test(persistence): pin list_in_window and list_for_customer predicates; make reconciliation fakes honest`.
- Stage files explicitly by path (never `git add -A` / `git add .`) — the working
  tree may hold unrelated local modifications that must never be committed.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add the invoice-window predicate integration test

In `backend/tests/integration/test_oltp_repositories.py`, add:

```python
def test_list_in_window_selects_by_period_start_within_window(session: Session) -> None:
    SqlAlchemyTenantRepository(session).add(_tenant("t_1"))
    SqlAlchemyTenantRepository(session).add(_tenant("t_2"))
    repo = SqlAlchemyInvoiceRepository(session)
    # In: period_start inside [Jan 1, Feb 1).
    repo.add(TenantId("t_1"), _invoice("t_1", "in_in", _window(2026, 1, 10, 2026, 2, 10)))
    # Out: overlaps the window but period_start precedes it — the partitioning
    # semantic: an invoice reconciles in the window containing its period_start.
    repo.add(TenantId("t_1"), _invoice("t_1", "in_straddle", _window(2025, 12, 15, 2026, 1, 15)))
    # Out: period_start == window.end (half-open [start, end)).
    repo.add(TenantId("t_1"), _invoice("t_1", "in_next", _window(2026, 2, 1, 2026, 3, 1)))
    # Out: another tenant's invoice inside the window (§11).
    repo.add(TenantId("t_2"), _invoice("t_2", "in_other", _window(2026, 1, 20, 2026, 2, 20)))
    session.flush()

    listed = repo.list_in_window(TenantId("t_1"), _WINDOW)
    assert [inv.id for inv in listed] == [InvoiceId("in_in")]
```

Add two small helpers near the existing `_plan` helper, in the same style:

```python
def _window(y1: int, m1: int, d1: int, y2: int, m2: int, d2: int) -> TimeWindow:
    return TimeWindow(datetime(y1, m1, d1, tzinfo=UTC), datetime(y2, m2, d2, tzinfo=UTC))


def _invoice(tid: str, iid: str, period: TimeWindow) -> Invoice:
    return Invoice(
        id=InvoiceId(iid),
        tenant_id=TenantId(tid),
        customer_id="cus_1",
        period=period,
        currency="USD",
        line_items=(),
    )
```

(If `Invoice` rejects empty `line_items`, copy the single-line-item construction
from `test_invoice_round_trips_with_line_items` at lines 64–84 instead.)

**Verify**: `uv run pytest tests/integration/test_oltp_repositories.py -q` → all
pass, including the new test.

### Step 2: Add the contract-scoping integration test

In the same file, add (extending the import block with
`SqlAlchemyContractRepository`, `Contract`, `ContractId` as needed):

```python
def test_list_for_customer_is_tenant_and_customer_scoped(session: Session) -> None:
    SqlAlchemyTenantRepository(session).add(_tenant("t_1"))
    SqlAlchemyTenantRepository(session).add(_tenant("t_2"))
    plans = SqlAlchemyPlanRepository(session)
    plans.add(TenantId("t_1"), _plan("t_1", "pl_1"))
    plans.add(TenantId("t_2"), _plan("t_2", "pl_2"))
    session.flush()  # plans must hit the DB before contracts reference them (FK)

    repo = SqlAlchemyContractRepository(session)
    repo.add(TenantId("t_1"), _contract("t_1", "con_match", "cus_1", "pl_1"))
    repo.add(TenantId("t_1"), _contract("t_1", "con_other_cus", "cus_2", "pl_1"))
    repo.add(TenantId("t_2"), _contract("t_2", "con_other_tenant", "cus_1", "pl_2"))
    session.flush()

    listed = repo.list_for_customer(TenantId("t_1"), "cus_1")
    assert [c.id for c in listed] == [ContractId("con_match")]


def _contract(tid: str, cid: str, customer_id: str, plan_id: str) -> Contract:
    return Contract(
        id=ContractId(cid),
        tenant_id=TenantId(tid),
        customer_id=customer_id,
        plan_id=PlanId(plan_id),
        term=_WINDOW,
    )
```

**Verify**: `uv run pytest tests/integration/test_oltp_repositories.py -q` → all
pass, including both new tests.

### Step 3: Make the unit fakes honor the real read contracts

In `backend/tests/unit/test_run_reconciliation.py`, change exactly the fake read
methods (keep signatures identical):

```python
# FakeInvoiceRepo — mirror the real predicate: period_start inside the window.
def list_in_window(self, tenant_id: TenantId, window: TimeWindow) -> Sequence[Invoice]:
    return [inv for inv in self._invoices if window.contains(inv.period.start)]

# FakeUsageStore — mirror the real store: only events inside the window.
def query(self, tenant_id: TenantId, window: TimeWindow) -> Sequence[UsageEvent]:
    return [e for e in self._events if window.contains(e.occurred_at)]
```

Leave `FakeContractRepo.list_for_customer` as-is (it already filters by
customer; the fakes are single-tenant, and tenant scoping is now pinned at the
integration layer by Step 2).

**Verify**: `uv run pytest tests/unit/test_run_reconciliation.py -q` → all pass.
If any existing test fails, inspect its seeded data: fix is legitimate ONLY if
the seed simply used an invoice/event trivially outside the run window and the
test's intent is unchanged by aligning the seed. Anything else is a STOP.

### Step 4: Full gates

**Verify** (from `backend/`, Docker running):

1. `uv run pytest -q` → all pass (expect the pre-existing single skip for
   `STRIPE_TEST_SECRET_KEY`).
2. `uv run mypy src tests` → no issues.
3. `uv run ruff check .` → passes. 4. `uv run black --check .` → unchanged.
5. `uv run lint-imports` → 4 contracts kept.

## Test plan

New tests (all described above): the invoice-window predicate test (in-window
selected; straddling, next-window-boundary, and cross-tenant rows excluded) and
the contract tenant+customer scoping test. Pattern to model:
`test_plan_round_trips` / `test_invoice_round_trips_with_line_items` in the same
file. Fake tightening in Step 3 is validated by the existing reconciliation unit
suite staying green.

## Done criteria

- [ ] `uv run pytest -m integration -q` exits 0 and the run count increased by 2
- [ ] `uv run pytest -m "not integration" -q` exits 0
- [ ] `uv run mypy src tests`, `uv run ruff check .`, `uv run black --check .`,
      `uv run lint-imports` all exit 0
- [ ] `git status` shows no modified files outside the two in-scope test files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The excerpts under "Current state" don't match the live code (drift).
- An existing unit test in `test_run_reconciliation.py` fails after Step 3 for a
  reason other than a seed lying trivially outside the run window — that would
  mean production behavior depends on the fakes' dishonesty, which is exactly
  the signal Plan 002 needs to know about.
- `Contract`/`Invoice` construction fails validation in a way the exemplar
  pattern doesn't resolve.
- You find yourself wanting to modify `repositories.py` — that is out of scope.

## Maintenance notes

- Plan 002 changes how `RunReconciliation` loads usage; it depends on Step 3's
  window-honest `FakeUsageStore` to write a meaningful failing test. Land this
  plan first.
- If keyset pagination or overlap semantics ever replace the `period_start`
  partitioning predicate (deferred decisions), the Step 1 test is the one that
  must be consciously rewritten — it exists to make that change loud, not to
  forbid it.
