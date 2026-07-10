# Plan 002: Load usage covering the full billing period of every reconciled invoice

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 231534d..HEAD -- backend/src/yieldfield/application/reconciliation/run_reconciliation.py backend/src/yieldfield/infrastructure/persistence/repositories.py backend/tests/unit/test_run_reconciliation.py`
> If any of these changed since this plan was written (Plan 001's test-file
> changes are expected and fine), compare the "Current state" excerpts against
> the live code before proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED — changes reconciliation output (the product's core numbers);
  mitigated by landing Plan 001's predicate pins first and by the
  characterization test in Step 2.
- **Depends on**: plans/001-money-path-read-predicate-tests.md (the unit fakes
  must honor windows or Step 2's test passes vacuously)
- **Category**: bug
- **Planned at**: commit `231534d`, 2026-07-07

## Why this matters

`RunReconciliation` selects invoices whose `period_start` lies inside the
reconciliation window, but loads usage events bounded by **the window**, then
attributes events to each invoice by `invoice.period.contains(occurred_at)`. Any
selected invoice whose billing period extends past `window.end` therefore
reconciles against **undercounted usage**: events between `window.end` and
`period_end` are inside the invoice's period but were never loaded. Undercounted
usage means `UNBILLED_USAGE` leakage (usage exceeding what was billed) is
under-detected — the product's headline output ("here is the money you're
missing") silently reports too little. Example: reconciling January
(`[Jan 1, Feb 1)`) with an invoice covering Jan 15–Feb 15 ignores all Feb 1–14
usage on that invoice.

The sibling asymmetry — the Stripe connector *ingests* by period overlap while
reconciliation *selects* by `period_start` — is deliberate partitioning (each
invoice reconciles exactly once, in the window containing its `period_start`)
but is documented nowhere. This plan fixes the usage-coverage defect and writes
the partitioning contract down; it does NOT change invoice selection.

## Current state

Relevant files:

- `backend/src/yieldfield/application/reconciliation/run_reconciliation.py` —
  the use-case to change (framework-pure application layer; it may import only
  domain types — `lint-imports` enforces this).
- `backend/src/yieldfield/infrastructure/persistence/repositories.py` —
  `list_in_window` gets a documentation comment only (lines 134–144).
- `backend/tests/unit/test_run_reconciliation.py` — where the new test goes;
  after Plan 001 its fakes filter invoices/events by window honestly.

The load-and-attribute code as it exists today (run_reconciliation.py:76-92):

```python
invoices = list(self._invoices.list_in_window(tenant_id, window))
invoices_by_customer = self._group_by_customer(invoices)
usage_by_customer = self._usage_by_customer(tenant_id, window)

findings: list[Finding] = []
for customer_id, customer_invoices in invoices_by_customer.items():
    plans_by_metric = self._plans_for_customer(tenant_id, customer_id)
    if not plans_by_metric:
        continue  # no known pricing for this customer — skip (unpriced usage is future work)
    customer_usage = usage_by_customer.get(customer_id, [])
    # Precondition: a customer's invoice periods do not overlap (true for Stripe billing
    # periods). An event is attributed to every invoice whose period contains it, so
    # overlapping periods would double-count the same usage across invoices.
    for invoice in customer_invoices:
        events_in_period = [
            event for event in customer_usage if invoice.period.contains(event.occurred_at)
        ]
```

`_usage_by_customer(tenant_id, window)` calls
`self._usage_events.query(tenant_id, window)` — the `UsageEventStore` port
(`backend/src/yieldfield/domain/billing/usage_event_store.py:20`):
`def query(self, tenant_id: TenantId, window: TimeWindow) -> Iterable[UsageEvent]`.

`TimeWindow` (`backend/src/yieldfield/domain/shared/time_window.py`) is a frozen
dataclass with tz-aware half-open `[start, end)`, `.contains(moment)`,
`.overlaps(other)`. Constructing one validates `end >= start`.

The matcher (`backend/src/yieldfield/domain/reconciliation/matching.py`) emits
`LeakageType.UNBILLED_USAGE` (line 96) when a metric's usage quantity exceeds the
invoiced quantity, and `LeakageType.MISRATED_LINE_ITEM` (line 124) — the second
compares line-item amount to quantity × plan price and is unaffected by this
change.

The connector-side overlap semantics being documented against
(`backend/src/yieldfield/infrastructure/connectors/stripe_billing/connector.py:101-103`):
invoices are yielded when `invoice.period.overlaps(window)`.

Repo conventions: docstrings cite spec sections ("(§4.2)", "(§8)"); the module
docstring of `run_reconciliation.py` maintains a "Simplifications (this slice;
named, not silent)" paragraph — extend it, don't create a new register. Commit
style: conventional with scope, one commit for the whole task.

## Commands you will need

All from `backend/` (Docker required for the full suite). Machine note: if `uv`
errors provisioning Python 3.12, set `$env:UV_PYTHON='3.14'` first (PowerShell;
see `ops/README.md`, "Local-dev note").

| Purpose | Command | Expected on success |
|---|---|---|
| The target test file | `uv run pytest tests/unit/test_run_reconciliation.py -q` | all pass |
| Unit tests | `uv run pytest -m "not integration" -q` | all pass |
| Full suite | `uv run pytest -q` | all pass (1 pre-existing skip) |
| Types | `uv run mypy src tests` | `Success: no issues` |
| Lint / format / boundaries | `uv run ruff check .` / `uv run black --check .` / `uv run lint-imports` | clean / unchanged / 4 kept |
| OpenAPI drift (surface unchanged — must stay clean) | `uv run python ../ops/scripts/export_openapi.py --check` | `up to date` |

## Scope

**In scope**:

- `backend/src/yieldfield/application/reconciliation/run_reconciliation.py`
- `backend/src/yieldfield/infrastructure/persistence/repositories.py` —
  comment/docstring on `list_in_window` ONLY (no predicate change)
- `backend/tests/unit/test_run_reconciliation.py`

**Out of scope** (do NOT touch):

- `list_in_window`'s WHERE clause — the `period_start` partitioning is the
  decided invoice-selection contract; this plan documents it, nothing more.
- The Stripe connector, the matcher (`matching.py`), the ClickHouse store, all
  API/webhook/worker code, migrations.
- Any new API surface — the OpenAPI contract must not change.

## Git workflow

- Branch: `advisor/002-reconciliation-usage-coverage`.
- One commit, e.g.
  `fix(reconciliation): load usage covering each selected invoice's full billing period`.
- Stage files explicitly by path (never `git add -A` / `git add .`).
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Write the failing characterization test (RED)

In `backend/tests/unit/test_run_reconciliation.py`, following the construction
style of the existing tests in that file (they build invoices/plans/events with
the module's helpers and run `RunReconciliation(...).run(tenant, window, rid)`),
add a test like:

- Reconciliation window: `[2026-01-01, 2026-02-01)` (tz-aware UTC).
- One plan: metric `"api_call"`, unit price `0.10 USD`.
- One invoice: `period_start = 2026-01-15`, `period_end = 2026-02-15`
  (period_start inside the window → selected), one line item for `api_call`
  with `quantity=50`, amount `5.00 USD`.
- Usage events for the same customer/metric: 100 units at `2026-01-20` (inside
  both window and period) and 40 units at `2026-02-05` (inside the invoice
  period, OUTSIDE the reconciliation window — the tail this plan fixes).
- Expected: one `UNBILLED_USAGE` finding for `140 − 50 = 90` unbilled units →
  amount `9.00 USD`.

Also pin the negative: an event at `2026-02-20` (outside the invoice period)
must not change the result.

**Verify**: `uv run pytest tests/unit/test_run_reconciliation.py -q` → exactly
this new test FAILS (it will compute 50 unbilled units / `5.00 USD` today,
because the Feb 5 event is never loaded). If it PASSES immediately, Plan 001's
window-honest `FakeUsageStore` is not in place — STOP.

### Step 2: Widen the usage-load window to cover selected invoice periods (GREEN)

In `run_reconciliation.py`, compute the usage query window from the selected
invoices before loading usage:

```python
invoices = list(self._invoices.list_in_window(tenant_id, window))
invoices_by_customer = self._group_by_customer(invoices)
usage_by_customer = self._usage_by_customer(tenant_id, _usage_coverage_window(window, invoices))
```

with a module-level pure helper (application layer — domain imports only):

```python
def _usage_coverage_window(window: TimeWindow, invoices: Sequence[Invoice]) -> TimeWindow:
    """The span usage must be loaded over so every selected invoice sees its FULL
    billing period (§4.2): selection is by period_start ∈ window, but a period may
    extend past window.end — usage in that tail belongs to the invoice."""
    if not invoices:
        return window
    start = min(window.start, min(inv.period.start for inv in invoices))
    end = max(window.end, max(inv.period.end for inv in invoices))
    return TimeWindow(start, end)
```

The per-invoice `invoice.period.contains(event.occurred_at)` attribution filter
at lines 90–92 stays exactly as is — it is what bounds each invoice to its own
period.

Update the module docstring's "Simplifications" paragraph: remove/adjust nothing
else, but add one clause documenting the invoice-selection partitioning (an
invoice reconciles in the window containing its `period_start`; contiguous
windows therefore reconcile every invoice exactly once; ingestion pulls by
period *overlap*, which is broader by design).

**Verify**: `uv run pytest tests/unit/test_run_reconciliation.py -q` → ALL pass,
including Step 1's test.

### Step 3: Document the partitioning contract at the predicate

In `repositories.py`, add a short comment (or docstring) on
`SqlAlchemyInvoiceRepository.list_in_window` stating: selection is by
`period_start` within the half-open window — the partitioning contract that
pairs with `RunReconciliation`'s full-period usage coverage; overlap-based
selection would double-reconcile straddling invoices across contiguous windows.
Match the file's comment register (short, cites §).

**Verify**: `uv run pytest tests/integration/test_oltp_repositories.py -q` →
all pass (Plan 001's predicate test unchanged and green).

### Step 4: Full gates

**Verify**: `uv run pytest -q` → all pass (1 pre-existing skip); then
`uv run mypy src tests`, `uv run ruff check .`, `uv run black --check .`,
`uv run lint-imports`, `uv run python ../ops/scripts/export_openapi.py --check`
→ all clean.

## Test plan

- New: the tail-usage characterization test + outside-period negative (Step 1),
  modeled on the existing tests in `test_run_reconciliation.py`.
- Regression net: the whole existing reconciliation suite (property-based money
  tests in `test_matching.py` are untouched — they call `reconcile_customer`
  directly), Plan 001's integration predicate pins, and the E2E money path.

## Done criteria

- [ ] The Step-1 test exists, failed before Step 2 (visible in your report), and
      passes after
- [ ] `uv run pytest -q` exits 0 (1 pre-existing skip)
- [ ] mypy / ruff / black / lint-imports / OpenAPI check all exit 0
- [ ] `git status` shows no modified files outside the three in-scope files
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The Step-1 test passes before any production change (fakes not window-honest
  → Plan 001 not landed or regressed).
- Any EXISTING test fails after Step 2 asserting the old narrower behavior —
  that means the window-bounded usage load was pinned somewhere as intended
  behavior, and the maintainer must arbitrate before you rewrite expectations.
- You find yourself changing `list_in_window`'s WHERE clause, the matcher, or
  the connector — all out of scope.
- `lint-imports` reports a broken contract after your edit (the helper must not
  pull infrastructure imports into the application layer).

## Maintenance notes

- The widened query makes the ClickHouse usage read span
  `max(period_end) − min(period_start)` instead of the bare window — bounded by
  invoice period lengths (~1 month typical). The deferred at-scale rework
  (streamed usage loads, audit PF-1) should preserve full-period coverage.
- Reviewer focus: the min/max span logic with empty invoices, and that the
  per-invoice `contains` filter still bounds attribution (no event leaks into a
  neighboring invoice).
- Deliberately deferred: overlap-selection + cross-window dedup as an
  alternative semantic — rejected here because immutable per-run findings
  (decision C) would double-report straddling invoices in two runs.
