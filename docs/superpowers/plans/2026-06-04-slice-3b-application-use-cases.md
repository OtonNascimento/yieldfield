# Plan 3B — Application Use-Cases Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure `application/` use-case layer that orchestrates the Slice-2/3A domain ports — ingest invoices, ingest usage events, run reconciliation, transition a finding — with no framework, no I/O, and no infrastructure imports.

**Architecture:** Each use-case is a small class whose constructor takes **domain ports** (Protocols) and whose single public method runs one use case (spec §4). Use-cases import **only** `yieldfield.domain` — enforced by the 4th import-linter contract (`application ⊥ infrastructure`). They are **job-unaware** (spec §3): the worker (Plan 3C) wraps them. All tests are pure unit tests against in-memory fakes — no Docker, no marker.

**Tech Stack:** Python 3.12, dataclasses + `Protocol` ports, pytest, mypy `--strict`, ruff, black, import-linter. Tooling runs via `uv` from `backend/`.

**Branch:** `slice-3-application-api-jobs` (HEAD `aeaffbf`, Plan 3A complete & green).

---

## Scope (strictly Plan 3B, per spec §15)

**In scope:** `application/errors.py`, `application/ingestion/` (`IngestInvoices`, `IngestUsageEvents`), `application/reconciliation/` (`RunReconciliation` orchestration), `application/findings/` (`TransitionFinding`) — pure, domain-ports-only, tested by unit (fake ports).

**Explicitly out of scope (deferred to Plan 3C):** FastAPI routers/DTOs/dependencies, webhooks, Celery tasks, the `run_as_job` wrapper, the `jobs`-table writes, OpenAPI emission, the `/ready` extension, and any E2E. 3B produces **no** API, **no** worker, **no** new infrastructure. It also writes **no** integration tests (the repos/cipher/store it depends on were integration-tested in 3A).

---

## Lessons from Plan 3A carried into 3B

1. **Fakes must implement the *full* Protocol surface.** mypy `--strict` checks a fake passed where a `Protocol` is expected for structural conformance. A `FakeInvoiceRepo` used as `InvoiceRepository` must define `add`/`get`/`list_in_window` — all fully annotated (strict requires annotations on every `def`). Half-fakes fail the type gate. (3A: `FakeConnectorStore`.)
2. **Validate/guard before mutating.** `TransitionFinding` must raise on an illegal transition **before** calling `update`, and never persist a not-found entity — mirroring 3A's "validate-before-persist" in the registration service.
3. **Test every error branch.** A use-case with two failure modes (not-found vs illegal-transition) gets a test for each — the 3A final review flagged exactly this kind of untested branch.
4. **Inject the clock and id-factory for determinism.** `RunReconciliation` takes a `clock` and a `finding_id_factory` with real defaults, so tests pin `executed_at` and finding ids exactly. (3A: the registration service's injected `id_factory`.)
5. **tz-aware datetimes only.** `Reconciliation.executed_at` raises if naive; the default clock returns `datetime.now(UTC)`.
6. **Pin error messages with `match=`** where the message carries the diagnostic (the offending id). (3A Task 12 review.)
7. **Idempotency is the repository's job, not the use-case's.** The use-case stays simple and calls the (already idempotent, 3A) `add`; convergence is verified at the financial-result level here and at the storage level by 3A's integration tests.

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/src/yieldfield/application/errors.py` | `ApplicationError` base + `EntityNotFoundError` (spec §4.4). Imports nothing outside stdlib — keeps `application ⊥ infrastructure`. |
| `backend/src/yieldfield/application/ingestion/ingest_invoices.py` | `IngestInvoices` use-case (spec §4.1): pull invoices → upsert → count. |
| `backend/src/yieldfield/application/ingestion/ingest_usage_events.py` | `IngestUsageEvents` use-case (spec §4.1): pull usage → append (idempotent OLAP) → count. |
| `backend/src/yieldfield/application/reconciliation/run_reconciliation.py` | `RunReconciliation` use-case (spec §4.2): the orchestration over the pure `reconcile_customer`, persisting one immutable `Reconciliation`. |
| `backend/src/yieldfield/application/findings/transition_finding.py` | `TransitionFinding` use-case (spec §4.3): load → domain transition → persist. One DRY use-case behind the four explicit 3C routes (decision D). |
| `backend/tests/unit/test_application_errors.py` | Unit test for the error hierarchy. |
| `backend/tests/unit/test_ingest_invoices.py` | Unit tests (fake connector + fake repo). |
| `backend/tests/unit/test_ingest_usage_events.py` | Unit tests (fake connector + fake store). |
| `backend/tests/unit/test_transition_finding.py` | Unit tests (fake finding repo). |
| `backend/tests/unit/test_run_reconciliation.py` | Unit tests (fake repos + store) — the money path, tested hardest. |

The four subpackage `__init__.py` files (`application/{ingestion,reconciliation,findings}/__init__.py` and `application/__init__.py`) **already exist and are empty** — leave them empty (no convenience re-exports; YAGNI). Plan 3C imports use-cases by their full module path (see "Interfaces 3C will consume").

---

## Conventions (apply to every task)

- **Run from `backend/`.** Tests: `uv run pytest <path> -q`. Types: `uv run mypy`. Lint: `uv run ruff check .`. Format: `uv run black .`. Import guard: `uv run lint-imports`.
- Every module starts with `from __future__ import annotations` and a short docstring citing the governing spec section.
- Line length 100. mypy `--strict` (every `def` fully annotated, including test fakes).
- Commit messages: Conventional Commits, ending the body with exactly:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
- TDD: write the failing test, run it red, implement the minimum, run it green, then commit.

---

## Task 1: Application error hierarchy

**Files:**
- Create: `backend/src/yieldfield/application/errors.py`
- Test: `backend/tests/unit/test_application_errors.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_application_errors.py`:

```python
"""Application-layer error hierarchy (§4.4)."""

from __future__ import annotations

from yieldfield.application.errors import ApplicationError, EntityNotFoundError


def test_entity_not_found_is_an_application_error() -> None:
    assert issubclass(EntityNotFoundError, ApplicationError)
    assert issubclass(ApplicationError, Exception)


def test_entity_not_found_carries_its_message() -> None:
    err = EntityNotFoundError("Finding 'f_1' not found.")
    assert str(err) == "Finding 'f_1' not found."
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_application_errors.py -q`
Expected: FAIL — `ModuleNotFoundError: yieldfield.application.errors`.

- [ ] **Step 3: Create the error module**

Create `backend/src/yieldfield/application/errors.py`:

```python
"""Application-layer errors (§4.4).

Use-case-level failures that the API (Plan 3C) maps onto the error envelope (§10). They are
distinct from domain rule violations (`DomainError`) and from infrastructure `PersistenceError`
— the application layer never imports infrastructure (4th import contract, §14), so the
infrastructure error is mapped at the API boundary, not re-raised here.
"""

from __future__ import annotations


class ApplicationError(Exception):
    """Base class for application/use-case errors."""


class EntityNotFoundError(ApplicationError):
    """A requested entity does not exist for the tenant (§4.4) → HTTP 404 in the API."""
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_application_errors.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/src/yieldfield/application/errors.py backend/tests/unit/test_application_errors.py
git commit -m "feat(application): EntityNotFoundError + ApplicationError base (§4.4)"
```

---

## Task 2: `IngestInvoices` use-case

**Files:**
- Create: `backend/src/yieldfield/application/ingestion/ingest_invoices.py`
- Test: `backend/tests/unit/test_ingest_invoices.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_ingest_invoices.py`:

```python
"""IngestInvoices pulls from the connector and upserts each invoice (§4.1)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from yieldfield.application.ingestion.ingest_invoices import IngestInvoices
from yieldfield.domain.billing.connector_port import ConnectorCredentials
from yieldfield.domain.billing.invoice import Invoice
from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.ids import InvoiceId, TenantId
from yieldfield.domain.shared.time_window import TimeWindow

TENANT = TenantId("t_1")
WINDOW = TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))


def _invoice(invoice_id: str, customer_id: str = "cus_1") -> Invoice:
    return Invoice(
        id=InvoiceId(invoice_id),
        tenant_id=TENANT,
        customer_id=customer_id,
        period=WINDOW,
        currency="USD",
        line_items=(),
    )


class FakeInvoiceRepo:
    def __init__(self) -> None:
        self.added: list[tuple[TenantId, Invoice]] = []

    def add(self, tenant_id: TenantId, invoice: Invoice) -> None:
        self.added.append((tenant_id, invoice))

    def get(self, tenant_id: TenantId, invoice_id: InvoiceId) -> Invoice | None:
        return None

    def list_in_window(self, tenant_id: TenantId, window: TimeWindow) -> Sequence[Invoice]:
        return []


class FakeConnector:
    def __init__(self, invoices: Sequence[Invoice]) -> None:
        self._invoices = invoices

    def authenticate(self, credentials: ConnectorCredentials) -> None:
        return None

    def pull_usage_events(self, window: TimeWindow) -> Iterable[UsageEvent]:
        return []

    def pull_invoices(self, window: TimeWindow) -> Iterable[Invoice]:
        return list(self._invoices)

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        return True


def test_ingests_all_pulled_invoices_and_returns_count() -> None:
    repo = FakeInvoiceRepo()
    connector = FakeConnector([_invoice("inv_1"), _invoice("inv_2")])
    count = IngestInvoices(repo).run(TENANT, WINDOW, connector)
    assert count == 2
    assert [inv.id for _, inv in repo.added] == [InvoiceId("inv_1"), InvoiceId("inv_2")]


def test_passes_tenant_scope_to_repository() -> None:
    repo = FakeInvoiceRepo()
    IngestInvoices(repo).run(TENANT, WINDOW, FakeConnector([_invoice("inv_1")]))
    assert repo.added[0][0] == TENANT


def test_empty_pull_returns_zero_and_adds_nothing() -> None:
    repo = FakeInvoiceRepo()
    count = IngestInvoices(repo).run(TENANT, WINDOW, FakeConnector([]))
    assert count == 0
    assert repo.added == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_ingest_invoices.py -q`
Expected: FAIL — `ModuleNotFoundError: yieldfield.application.ingestion.ingest_invoices`.

- [ ] **Step 3: Create the use-case**

Create `backend/src/yieldfield/application/ingestion/ingest_invoices.py`:

```python
"""Ingest invoices (§4.1) — pull from a connector, upsert into the OLTP repository.

Pure orchestration over domain ports: it depends on the `ConnectorPort` and
`InvoiceRepository` abstractions, never a concrete adapter or framework. Idempotency is the
repository's job (upsert-by-id, §8); this use-case just drives it. Job-unaware (§3).
"""

from __future__ import annotations

from yieldfield.domain.billing.connector_port import ConnectorPort
from yieldfield.domain.billing.repositories import InvoiceRepository
from yieldfield.domain.shared.ids import TenantId
from yieldfield.domain.shared.time_window import TimeWindow


class IngestInvoices:
    def __init__(self, invoices: InvoiceRepository) -> None:
        self._invoices = invoices

    def run(self, tenant_id: TenantId, window: TimeWindow, connector: ConnectorPort) -> int:
        """Pull invoices issued in `window`, upsert each, return the count ingested."""
        count = 0
        for invoice in connector.pull_invoices(window):
            self._invoices.add(tenant_id, invoice)
            count += 1
        return count
```

- [ ] **Step 4: Run to verify it passes + types**

Run:
```bash
uv run pytest tests/unit/test_ingest_invoices.py -q
uv run mypy
```
Expected: tests PASS (3 passed); mypy `Success`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/yieldfield/application/ingestion/ingest_invoices.py backend/tests/unit/test_ingest_invoices.py
git commit -m "feat(application): IngestInvoices use-case over domain ports (§4.1)"
```

---

## Task 3: `IngestUsageEvents` use-case

**Files:**
- Create: `backend/src/yieldfield/application/ingestion/ingest_usage_events.py`
- Test: `backend/tests/unit/test_ingest_usage_events.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_ingest_usage_events.py`:

```python
"""IngestUsageEvents pulls from the connector and appends to the OLAP store (§4.1)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal

from yieldfield.application.ingestion.ingest_usage_events import IngestUsageEvents
from yieldfield.domain.billing.connector_port import ConnectorCredentials
from yieldfield.domain.billing.invoice import Invoice
from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.ids import TenantId, UsageEventId
from yieldfield.domain.shared.time_window import TimeWindow

TENANT = TenantId("t_1")
WINDOW = TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))


def _event(event_id: str, customer_id: str = "cus_1") -> UsageEvent:
    return UsageEvent(
        id=UsageEventId(event_id),
        tenant_id=TENANT,
        customer_id=customer_id,
        metric="api_calls",
        quantity=Decimal("1"),
        occurred_at=datetime(2026, 1, 15, tzinfo=UTC),
    )


class FakeUsageStore:
    def __init__(self) -> None:
        self.appended: list[tuple[TenantId, list[UsageEvent]]] = []

    def append(self, tenant_id: TenantId, events: Iterable[UsageEvent]) -> None:
        self.appended.append((tenant_id, list(events)))

    def query(self, tenant_id: TenantId, window: TimeWindow) -> Iterable[UsageEvent]:
        return []


class FakeConnector:
    def __init__(self, events: list[UsageEvent]) -> None:
        self._events = events

    def authenticate(self, credentials: ConnectorCredentials) -> None:
        return None

    def pull_usage_events(self, window: TimeWindow) -> Iterable[UsageEvent]:
        return list(self._events)

    def pull_invoices(self, window: TimeWindow) -> Iterable[Invoice]:
        return []

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        return True


def test_appends_all_pulled_events_and_returns_count() -> None:
    store = FakeUsageStore()
    connector = FakeConnector([_event("u_1"), _event("u_2")])
    count = IngestUsageEvents(store).run(TENANT, WINDOW, connector)
    assert count == 2
    assert len(store.appended) == 1  # one batch append, not one call per event
    assert [e.id for e in store.appended[0][1]] == [UsageEventId("u_1"), UsageEventId("u_2")]


def test_passes_tenant_scope_to_store() -> None:
    store = FakeUsageStore()
    IngestUsageEvents(store).run(TENANT, WINDOW, FakeConnector([_event("u_1")]))
    assert store.appended[0][0] == TENANT


def test_empty_pull_returns_zero() -> None:
    store = FakeUsageStore()
    count = IngestUsageEvents(store).run(TENANT, WINDOW, FakeConnector([]))
    assert count == 0
    assert store.appended == [(TENANT, [])]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_ingest_usage_events.py -q`
Expected: FAIL — `ModuleNotFoundError: yieldfield.application.ingestion.ingest_usage_events`.

- [ ] **Step 3: Create the use-case**

Create `backend/src/yieldfield/application/ingestion/ingest_usage_events.py`:

```python
"""Ingest usage events (§4.1) — pull from a connector, append to the OLAP store.

Appends in a single batch (the store's `append` takes an iterable); idempotency is the
store's job (ReplacingMergeTree on the deterministic event id, §8). Job-unaware (§3).
"""

from __future__ import annotations

from yieldfield.domain.billing.connector_port import ConnectorPort
from yieldfield.domain.billing.usage_event_store import UsageEventStore
from yieldfield.domain.shared.ids import TenantId
from yieldfield.domain.shared.time_window import TimeWindow


class IngestUsageEvents:
    def __init__(self, usage_events: UsageEventStore) -> None:
        self._usage_events = usage_events

    def run(self, tenant_id: TenantId, window: TimeWindow, connector: ConnectorPort) -> int:
        """Pull usage events in `window`, append them, return the count ingested."""
        events = list(connector.pull_usage_events(window))
        self._usage_events.append(tenant_id, events)
        return len(events)
```

- [ ] **Step 4: Run to verify it passes + types**

Run:
```bash
uv run pytest tests/unit/test_ingest_usage_events.py -q
uv run mypy
```
Expected: tests PASS (3 passed); mypy `Success`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/yieldfield/application/ingestion/ingest_usage_events.py backend/tests/unit/test_ingest_usage_events.py
git commit -m "feat(application): IngestUsageEvents use-case over domain ports (§4.1)"
```

---

## Task 4: `TransitionFinding` use-case

**Files:**
- Create: `backend/src/yieldfield/application/findings/transition_finding.py`
- Test: `backend/tests/unit/test_transition_finding.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_transition_finding.py`:

```python
"""TransitionFinding loads, applies a domain transition, and persists (§4.3)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from yieldfield.application.errors import EntityNotFoundError
from yieldfield.application.findings.transition_finding import TransitionFinding
from yieldfield.domain.findings.finding import Finding, FindingLineage
from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.severity import Severity
from yieldfield.domain.shared.errors import InvalidFindingTransitionError
from yieldfield.domain.shared.ids import FindingId, ReconciliationId, TenantId
from yieldfield.domain.shared.money import Money

TENANT = TenantId("t_1")


def _finding(status: RecoveryStatus = RecoveryStatus.NEW) -> Finding:
    return Finding(
        id=FindingId("f_1"),
        tenant_id=TENANT,
        reconciliation_id=ReconciliationId("r_1"),
        customer_id="cus_1",
        metric="api_calls",
        leakage_type=LeakageType.UNBILLED_USAGE,
        severity=Severity.LOW,
        amount=Money.of("10.00", "USD"),
        status=status,
        lineage=FindingLineage(rule_version="reconciliation-v1"),
        explanation="10 api_calls were not billed.",
    )


class FakeFindingRepo:
    def __init__(self, finding: Finding | None) -> None:
        self._finding = finding
        self.updated: list[Finding] = []

    def get(self, tenant_id: TenantId, finding_id: FindingId) -> Finding | None:
        if self._finding is not None and self._finding.id == finding_id:
            return self._finding
        return None

    def list_for_reconciliation(
        self, tenant_id: TenantId, reconciliation_id: ReconciliationId
    ) -> Sequence[Finding]:
        return [] if self._finding is None else [self._finding]

    def update(self, tenant_id: TenantId, finding: Finding) -> None:
        self.updated.append(finding)


def test_review_transitions_new_to_reviewed_and_persists() -> None:
    repo = FakeFindingRepo(_finding(RecoveryStatus.NEW))
    result = TransitionFinding(repo).run(TENANT, FindingId("f_1"), RecoveryStatus.REVIEWED)
    assert result.status is RecoveryStatus.REVIEWED
    assert repo.updated == [result]


def test_missing_finding_raises_entity_not_found() -> None:
    repo = FakeFindingRepo(None)
    with pytest.raises(EntityNotFoundError, match="f_1"):
        TransitionFinding(repo).run(TENANT, FindingId("f_1"), RecoveryStatus.REVIEWED)


def test_illegal_transition_raises_and_does_not_persist() -> None:
    repo = FakeFindingRepo(_finding(RecoveryStatus.NEW))
    # NEW -> CONFIRMED is illegal (must go through REVIEWED, decision D).
    with pytest.raises(InvalidFindingTransitionError):
        TransitionFinding(repo).run(TENANT, FindingId("f_1"), RecoveryStatus.CONFIRMED)
    assert repo.updated == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_transition_finding.py -q`
Expected: FAIL — `ModuleNotFoundError: yieldfield.application.findings.transition_finding`.

- [ ] **Step 3: Create the use-case**

Create `backend/src/yieldfield/application/findings/transition_finding.py`:

```python
"""Transition a finding (§4.3) — the one DRY use-case behind the four explicit routes.

Loads the finding (→ EntityNotFoundError if absent), applies the domain lifecycle transition
(`Finding.transition_to`, which raises InvalidFindingTransitionError on an illegal edge), and
persists the result. The illegal-transition guard fires BEFORE `update`, so an invalid request
never writes (decision D). Job-unaware (§3).
"""

from __future__ import annotations

from yieldfield.application.errors import EntityNotFoundError
from yieldfield.domain.findings.finding import Finding
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.repositories import FindingRepository
from yieldfield.domain.shared.ids import FindingId, TenantId


class TransitionFinding:
    def __init__(self, findings: FindingRepository) -> None:
        self._findings = findings

    def run(self, tenant_id: TenantId, finding_id: FindingId, target: RecoveryStatus) -> Finding:
        """Apply `target` to the finding and persist; return the updated finding."""
        finding = self._findings.get(tenant_id, finding_id)
        if finding is None:
            raise EntityNotFoundError(f"Finding {finding_id!r} not found.")
        updated = finding.transition_to(target)  # raises on an illegal transition, before any write
        self._findings.update(tenant_id, updated)
        return updated
```

- [ ] **Step 4: Run to verify it passes + types**

Run:
```bash
uv run pytest tests/unit/test_transition_finding.py -q
uv run mypy
```
Expected: tests PASS (3 passed); mypy `Success`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/yieldfield/application/findings/transition_finding.py backend/tests/unit/test_transition_finding.py
git commit -m "feat(application): TransitionFinding use-case (load/transition/persist) (§4.3)"
```

---

## Task 5: `RunReconciliation` orchestration (the money path)

> The deepest-tested use-case (spec §12). It wires the OLTP/OLAP ports into the pure
> `reconcile_customer` engine and persists one immutable, append-only `Reconciliation`
> (decision C). The whole orchestration lands in one task; tests are written first (red), the
> full algorithm second (green).

**Files:**
- Create: `backend/src/yieldfield/application/reconciliation/run_reconciliation.py`
- Test: `backend/tests/unit/test_run_reconciliation.py`

- [ ] **Step 1: Write the failing tests (core money-path + breadth)**

Create `backend/tests/unit/test_run_reconciliation.py`:

```python
"""RunReconciliation orchestration (§4.2) — the money path, tested hardest.

Fakes stand in for the OLTP repos and the OLAP store; the pure matching engine is exercised
through the use-case. Clock and finding-id factory are injected for deterministic assertions.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from itertools import count

from yieldfield.application.reconciliation.run_reconciliation import RunReconciliation
from yieldfield.domain.billing.contract import Contract
from yieldfield.domain.billing.invoice import Invoice, InvoiceLineItem
from yieldfield.domain.billing.plan import Plan
from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.reconciliation.reconciliation import Reconciliation
from yieldfield.domain.shared.ids import (
    ContractId,
    FindingId,
    InvoiceId,
    InvoiceLineItemId,
    PlanId,
    ReconciliationId,
    TenantId,
    UsageEventId,
)
from yieldfield.domain.shared.money import Money
from yieldfield.domain.shared.time_window import TimeWindow

TENANT = TenantId("t_1")
RECON = ReconciliationId("r_1")
WINDOW = TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC))
JAN = TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))
FEB = TimeWindow(datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC))
FIXED_NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def _counter_ids() -> Callable[[], FindingId]:
    counter = count(1)
    return lambda: FindingId(f"f_{next(counter)}")


def _plan(plan_id: str, metric: str, unit_price: str) -> Plan:
    return Plan(
        id=PlanId(plan_id),
        tenant_id=TENANT,
        name=f"Plan {metric}",
        metric=metric,
        unit_price=Money.of(unit_price, "USD"),
    )


def _contract(contract_id: str, customer_id: str, plan_id: str) -> Contract:
    return Contract(
        id=ContractId(contract_id),
        tenant_id=TENANT,
        customer_id=customer_id,
        plan_id=PlanId(plan_id),
        term=WINDOW,
    )


def _line(metric: str, quantity: str, amount: str, lid: str = "li_1") -> InvoiceLineItem:
    return InvoiceLineItem(
        id=InvoiceLineItemId(lid),
        metric=metric,
        quantity=Decimal(quantity),
        amount=Money.of(amount, "USD"),
    )


def _invoice(
    invoice_id: str,
    customer_id: str,
    *lines: InvoiceLineItem,
    period: TimeWindow = JAN,
) -> Invoice:
    return Invoice(
        id=InvoiceId(invoice_id),
        tenant_id=TENANT,
        customer_id=customer_id,
        period=period,
        currency="USD",
        line_items=lines,
    )


def _event(event_id: str, customer_id: str, metric: str, quantity: str, at: datetime) -> UsageEvent:
    return UsageEvent(
        id=UsageEventId(event_id),
        tenant_id=TENANT,
        customer_id=customer_id,
        metric=metric,
        quantity=Decimal(quantity),
        occurred_at=at,
    )


class FakeInvoiceRepo:
    def __init__(self, invoices: list[Invoice]) -> None:
        self._invoices = invoices

    def add(self, tenant_id: TenantId, invoice: Invoice) -> None:
        return None

    def get(self, tenant_id: TenantId, invoice_id: InvoiceId) -> Invoice | None:
        return None

    def list_in_window(self, tenant_id: TenantId, window: TimeWindow) -> Sequence[Invoice]:
        return list(self._invoices)


class FakeUsageStore:
    def __init__(self, events: list[UsageEvent]) -> None:
        self._events = events

    def append(self, tenant_id: TenantId, events: Iterable[UsageEvent]) -> None:
        return None

    def query(self, tenant_id: TenantId, window: TimeWindow) -> Sequence[UsageEvent]:
        return list(self._events)


class FakeContractRepo:
    def __init__(self, contracts: list[Contract]) -> None:
        self._contracts = contracts

    def add(self, tenant_id: TenantId, contract: Contract) -> None:
        return None

    def get(self, tenant_id: TenantId, contract_id: ContractId) -> Contract | None:
        return None

    def list_for_customer(self, tenant_id: TenantId, customer_id: str) -> Sequence[Contract]:
        return [c for c in self._contracts if c.customer_id == customer_id]


class FakePlanRepo:
    def __init__(self, plans: list[Plan]) -> None:
        self._plans = {p.id: p for p in plans}

    def add(self, tenant_id: TenantId, plan: Plan) -> None:
        return None

    def get(self, tenant_id: TenantId, plan_id: PlanId) -> Plan | None:
        return self._plans.get(plan_id)

    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Plan]:
        return list(self._plans.values())


class FakeReconRepo:
    def __init__(self) -> None:
        self.saved: list[Reconciliation] = []

    def add(self, tenant_id: TenantId, reconciliation: Reconciliation) -> None:
        self.saved.append(reconciliation)

    def get(
        self, tenant_id: TenantId, reconciliation_id: ReconciliationId
    ) -> Reconciliation | None:
        for r in self.saved:
            if r.id == reconciliation_id:
                return r
        return None

    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Reconciliation]:
        return list(self.saved)


def _service(
    *,
    invoices: list[Invoice],
    events: list[UsageEvent],
    contracts: list[Contract],
    plans: list[Plan],
    recon_repo: FakeReconRepo,
    clock: Callable[[], datetime] = lambda: FIXED_NOW,
) -> RunReconciliation:
    return RunReconciliation(
        FakeInvoiceRepo(invoices),
        FakeUsageStore(events),
        FakeContractRepo(contracts),
        FakePlanRepo(plans),
        recon_repo,
        finding_id_factory=_counter_ids(),
        clock=clock,
    )


# ── core money path ──────────────────────────────────────────────────────────
def test_unbilled_usage_creates_finding_and_persists_once() -> None:
    repo = FakeReconRepo()
    service = _service(
        invoices=[_invoice("inv_1", "cus_1")],  # nothing billed
        events=[_event("u_1", "cus_1", "api_calls", "100", datetime(2026, 1, 15, tzinfo=UTC))],
        contracts=[_contract("con_1", "cus_1", "p_1")],
        plans=[_plan("p_1", "api_calls", "0.10")],
        recon_repo=repo,
    )
    result = service.run(TENANT, WINDOW, RECON)
    assert result.id == RECON
    assert result.finding_count == 1
    assert result.findings[0].leakage_type is LeakageType.UNBILLED_USAGE
    assert result.total_leakage() == Money.of("10.00", "USD")
    assert result.currency == "USD"
    assert result.rule_version == "reconciliation-v1"
    assert result.executed_at == FIXED_NOW
    assert repo.saved == [result]  # persisted exactly once


def test_misrated_line_item_is_detected() -> None:
    repo = FakeReconRepo()
    service = _service(
        invoices=[_invoice("inv_1", "cus_1", _line("api_calls", "100", "5.00"))],  # underpriced
        events=[_event("u_1", "cus_1", "api_calls", "100", datetime(2026, 1, 15, tzinfo=UTC))],
        contracts=[_contract("con_1", "cus_1", "p_1")],
        plans=[_plan("p_1", "api_calls", "0.10")],  # expected $10, billed $5
        recon_repo=repo,
    )
    result = service.run(TENANT, WINDOW, RECON)
    assert result.finding_count == 1
    assert result.findings[0].leakage_type is LeakageType.MISRATED_LINE_ITEM
    assert result.total_leakage() == Money.of("5.00", "USD")


def test_correctly_billed_yields_empty_persisted_run() -> None:
    repo = FakeReconRepo()
    service = _service(
        invoices=[_invoice("inv_1", "cus_1", _line("api_calls", "100", "10.00"))],
        events=[_event("u_1", "cus_1", "api_calls", "100", datetime(2026, 1, 15, tzinfo=UTC))],
        contracts=[_contract("con_1", "cus_1", "p_1")],
        plans=[_plan("p_1", "api_calls", "0.10")],
        recon_repo=repo,
    )
    result = service.run(TENANT, WINDOW, RECON)
    assert result.finding_count == 0
    assert result.total_leakage() == Money.zero("USD")
    assert repo.saved == [result]


def test_injected_id_factory_numbers_findings_deterministically() -> None:
    service = _service(
        invoices=[_invoice("inv_1", "cus_1")],
        events=[_event("u_1", "cus_1", "api_calls", "100", datetime(2026, 1, 15, tzinfo=UTC))],
        contracts=[_contract("con_1", "cus_1", "p_1")],
        plans=[_plan("p_1", "api_calls", "0.10")],
        recon_repo=FakeReconRepo(),
    )
    result = service.run(TENANT, WINDOW, RECON)
    assert result.findings[0].id == FindingId("f_1")


# ── breadth / orchestration edges ────────────────────────────────────────────
def test_each_customer_is_reconciled_against_its_own_plan() -> None:
    service = _service(
        invoices=[_invoice("inv_1", "cus_1"), _invoice("inv_2", "cus_2")],
        events=[
            _event("u_1", "cus_1", "api_calls", "100", datetime(2026, 1, 15, tzinfo=UTC)),
            _event("u_2", "cus_2", "storage", "5", datetime(2026, 1, 15, tzinfo=UTC)),
        ],
        contracts=[_contract("con_1", "cus_1", "p_1"), _contract("con_2", "cus_2", "p_2")],
        plans=[_plan("p_1", "api_calls", "0.10"), _plan("p_2", "storage", "1.00")],
        recon_repo=FakeReconRepo(),
    )
    result = service.run(TENANT, WINDOW, RECON)
    by_customer = {f.customer_id: f for f in result.findings}
    assert by_customer["cus_1"].metric == "api_calls"
    assert by_customer["cus_1"].amount == Money.of("10.00", "USD")
    assert by_customer["cus_2"].metric == "storage"
    assert by_customer["cus_2"].amount == Money.of("5.00", "USD")
    assert result.total_leakage() == Money.of("15.00", "USD")


def test_usage_outside_an_invoice_period_is_excluded() -> None:
    # Window spans Jan+Feb; invoice covers Jan only. The Feb event must not be attributed.
    service = _service(
        invoices=[_invoice("inv_1", "cus_1", period=JAN)],
        events=[
            _event("u_1", "cus_1", "api_calls", "100", datetime(2026, 1, 15, tzinfo=UTC)),
            _event("u_2", "cus_1", "api_calls", "50", datetime(2026, 2, 15, tzinfo=UTC)),
        ],
        contracts=[_contract("con_1", "cus_1", "p_1")],
        plans=[_plan("p_1", "api_calls", "0.10")],
        recon_repo=FakeReconRepo(),
    )
    result = service.run(TENANT, WINDOW, RECON)
    assert result.total_leakage() == Money.of("10.00", "USD")  # only the 100 in Jan


def test_usage_is_attributed_to_the_invoice_whose_period_contains_it() -> None:
    service = _service(
        invoices=[
            _invoice("inv_jan", "cus_1", period=JAN),
            _invoice("inv_feb", "cus_1", period=FEB),
        ],
        events=[
            _event("u_1", "cus_1", "api_calls", "100", datetime(2026, 1, 15, tzinfo=UTC)),
            _event("u_2", "cus_1", "api_calls", "30", datetime(2026, 2, 15, tzinfo=UTC)),
        ],
        contracts=[_contract("con_1", "cus_1", "p_1")],
        plans=[_plan("p_1", "api_calls", "0.10")],
        recon_repo=FakeReconRepo(),
    )
    result = service.run(TENANT, WINDOW, RECON)
    amounts = sorted(f.amount.amount for f in result.findings)
    assert amounts == [Decimal("3.00"), Decimal("10.00")]  # Feb 30→$3, Jan 100→$10
    assert result.total_leakage() == Money.of("13.00", "USD")


def test_empty_window_persists_an_empty_usd_run() -> None:
    repo = FakeReconRepo()
    result = _service(
        invoices=[], events=[], contracts=[], plans=[], recon_repo=repo
    ).run(TENANT, WINDOW, RECON)
    assert result.finding_count == 0
    assert result.currency == "USD"
    assert result.total_leakage() == Money.zero("USD")
    assert repo.saved == [result]


def test_rerun_with_same_id_produces_the_same_financial_result() -> None:
    # Convergence at the financial level: same inputs + same reconciliation_id ⇒ same findings/total.
    # (Storage-level idempotency on reconciliation_id is the repository's job, integration-tested in 3A.)
    def make() -> RunReconciliation:
        return _service(
            invoices=[_invoice("inv_1", "cus_1")],
            events=[_event("u_1", "cus_1", "api_calls", "100", datetime(2026, 1, 15, tzinfo=UTC))],
            contracts=[_contract("con_1", "cus_1", "p_1")],
            plans=[_plan("p_1", "api_calls", "0.10")],
            recon_repo=FakeReconRepo(),
        )

    first = make().run(TENANT, WINDOW, RECON)
    second = make().run(TENANT, WINDOW, RECON)
    assert first.total_leakage() == second.total_leakage()
    assert [(f.metric, f.leakage_type, f.amount) for f in first.findings] == [
        (f.metric, f.leakage_type, f.amount) for f in second.findings
    ]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_run_reconciliation.py -q`
Expected: FAIL — `ModuleNotFoundError: yieldfield.application.reconciliation.run_reconciliation`.

- [ ] **Step 3: Create the use-case (full orchestration)**

Create `backend/src/yieldfield/application/reconciliation/run_reconciliation.py`:

```python
"""Run reconciliation (§4.2) — orchestration over the pure matching rules.

Loads the tenant's invoices + usage for a window, attributes the correct plan per customer from
their contracts, runs the pure `reconcile_customer` per (customer, invoice) — selecting that
customer's usage whose `occurred_at` falls within the invoice's billing period — and persists one
immutable `Reconciliation` (decision C). Idempotency on `reconciliation_id` is the repository's
job (§8); a fresh id is a new historical run. Job-unaware (§3).

Simplifications (this slice; named, not silent): a customer's plans are taken from all of that
customer's contracts (last contract wins per metric — term-based disambiguation is future work);
currency is taken from the window's invoices, defaulting to USD for an empty window (§4.2);
uninvoiced usage and mixed-currency are out of scope (§13).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import uuid4

from yieldfield.domain.billing.invoice import Invoice
from yieldfield.domain.billing.plan import Plan
from yieldfield.domain.billing.repositories import (
    ContractRepository,
    InvoiceRepository,
    PlanRepository,
)
from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.billing.usage_event_store import UsageEventStore
from yieldfield.domain.findings.finding import Finding
from yieldfield.domain.reconciliation.matching import DEFAULT_RULE_VERSION, reconcile_customer
from yieldfield.domain.reconciliation.reconciliation import Reconciliation
from yieldfield.domain.reconciliation.repositories import ReconciliationRepository
from yieldfield.domain.shared.ids import FindingId, ReconciliationId, TenantId
from yieldfield.domain.shared.time_window import TimeWindow

_DEFAULT_CURRENCY = "USD"


def _default_finding_id() -> FindingId:
    return FindingId(str(uuid4()))


def _utcnow() -> datetime:
    return datetime.now(UTC)


class RunReconciliation:
    def __init__(
        self,
        invoices: InvoiceRepository,
        usage_events: UsageEventStore,
        contracts: ContractRepository,
        plans: PlanRepository,
        reconciliations: ReconciliationRepository,
        *,
        finding_id_factory: Callable[[], FindingId] = _default_finding_id,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._invoices = invoices
        self._usage_events = usage_events
        self._contracts = contracts
        self._plans = plans
        self._reconciliations = reconciliations
        self._finding_id_factory = finding_id_factory
        self._clock = clock

    def run(
        self,
        tenant_id: TenantId,
        window: TimeWindow,
        reconciliation_id: ReconciliationId,
        rule_version: str = DEFAULT_RULE_VERSION,
    ) -> Reconciliation:
        """Reconcile `window` for `tenant_id`, persist one Reconciliation, and return it."""
        invoices = list(self._invoices.list_in_window(tenant_id, window))
        invoices_by_customer = self._group_by_customer(invoices)
        usage_by_customer = self._usage_by_customer(tenant_id, window)

        findings: list[Finding] = []
        for customer_id, customer_invoices in invoices_by_customer.items():
            plans_by_metric = self._plans_for_customer(tenant_id, customer_id)
            if not plans_by_metric:
                continue  # no known pricing for this customer — skip (unpriced usage is future work)
            customer_usage = usage_by_customer.get(customer_id, [])
            for invoice in customer_invoices:
                events_in_period = [
                    event
                    for event in customer_usage
                    if invoice.period.contains(event.occurred_at)
                ]
                findings.extend(
                    reconcile_customer(
                        tenant_id=tenant_id,
                        reconciliation_id=reconciliation_id,
                        customer_id=customer_id,
                        usage_events=events_in_period,
                        invoice=invoice,
                        plans_by_metric=plans_by_metric,
                        id_factory=self._finding_id_factory,
                        rule_version=rule_version,
                    )
                )

        currency = invoices[0].currency if invoices else _DEFAULT_CURRENCY
        reconciliation = Reconciliation(
            id=reconciliation_id,
            tenant_id=tenant_id,
            window=window,
            currency=currency,
            executed_at=self._clock(),
            rule_version=rule_version,
            findings=tuple(findings),
        )
        self._reconciliations.add(tenant_id, reconciliation)
        return reconciliation

    @staticmethod
    def _group_by_customer(invoices: Sequence[Invoice]) -> dict[str, list[Invoice]]:
        grouped: dict[str, list[Invoice]] = {}
        for invoice in invoices:
            grouped.setdefault(invoice.customer_id, []).append(invoice)
        return grouped

    def _usage_by_customer(
        self, tenant_id: TenantId, window: TimeWindow
    ) -> dict[str, list[UsageEvent]]:
        usage_by_customer: dict[str, list[UsageEvent]] = {}
        for event in self._usage_events.query(tenant_id, window):
            usage_by_customer.setdefault(event.customer_id, []).append(event)
        return usage_by_customer

    def _plans_for_customer(self, tenant_id: TenantId, customer_id: str) -> dict[str, Plan]:
        plans_by_metric: dict[str, Plan] = {}
        for contract in self._contracts.list_for_customer(tenant_id, customer_id):
            plan = self._plans.get(tenant_id, contract.plan_id)
            if plan is not None:
                plans_by_metric[plan.metric] = plan
        return plans_by_metric
```

- [ ] **Step 4: Run to verify it passes + types**

Run:
```bash
uv run pytest tests/unit/test_run_reconciliation.py -q
uv run mypy
```
Expected: tests PASS (9 passed); mypy `Success`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/yieldfield/application/reconciliation/run_reconciliation.py backend/tests/unit/test_run_reconciliation.py
git commit -m "feat(application): RunReconciliation orchestration over domain ports (§4.2)"
```

---

## Task 6: Full 3B verification gate

**Files:** none (verification only).

- [ ] **Step 1: Run every static + unit gate**

Run from `backend/`:
```bash
uv run ruff check .
uv run black --check .
uv run mypy
uv run lint-imports
uv run pytest tests/unit -q
```
Expected: ruff `All checks passed!`; black all unchanged; mypy `Success`; import-linter `Contracts: 4 kept, 0 broken.` (the 4th — `application ⊥ infrastructure` — is the one this plan most exercises); unit tests all PASS (the prior 151 **+ 20 new** application tests — see the count note below).

> Count note: Task 1 adds 2, Task 2 adds 3, Task 3 adds 3, Task 4 adds 3, Task 5 adds 9 → **20 new unit tests**. Combined with the 151 unit tests green at HEAD `aeaffbf`, expect **171 passed**.

- [ ] **Step 2: Confirm the architecture boundary explicitly**

Run from `backend/`:
```bash
uv run python -c "import yieldfield.application.reconciliation.run_reconciliation, yieldfield.application.ingestion.ingest_invoices, yieldfield.application.ingestion.ingest_usage_events, yieldfield.application.findings.transition_finding, yieldfield.application.errors; print('application imports clean')"
```
Expected: prints `application imports clean` with no error. (The authoritative boundary check is `lint-imports` in Step 1; this is a fast smoke import.)

- [ ] **Step 3: Confirm the Docker-backed suite still passes (no regression)**

Docker is optional here — 3B added no integration tests and touched no infrastructure. If Docker is running, confirm no regression:
```bash
uv run pytest tests/integration -q -m integration
```
Expected: unchanged from 3A — `16 passed, 1 skipped`. If Docker is unavailable, skip this step (the integration suite is unaffected by application-only changes).

- [ ] **Step 4: Confirm and report**

3B is complete when Steps 1–2 are green. Report: the four use-cases (`IngestInvoices`, `IngestUsageEvents`, `RunReconciliation`, `TransitionFinding`) and `EntityNotFoundError` are in place, pure (domain-ports-only), and unit-tested — ready for Plan 3C (API + webhooks + workers + OpenAPI) to compose them.

---

## Assumptions (named, not silent)

1. **Currency for an empty window defaults to `USD`.** With no invoices there are no findings, so `Reconciliation.currency` only feeds `total_leakage()` (which is zero). Resolving currency from configuration/tenant is future work (spec §4.2 calls this a 3B implementation detail).
2. **A customer's plans come from all of that customer's contracts; last contract wins per metric.** Contract `term` is **not** used to disambiguate overlapping contracts this slice (spec §4.2 says "build plans_by_metric from that customer's Contracts" without term selection). Term-based selection is future work.
3. **Usage with no covering invoice is ignored** (spec §4.2 / §17): a dedicated "uninvoiced usage" rule is a future strategy. The orchestration only reconciles usage that falls within an existing invoice's period.
4. **`rule_version` defaults to `DEFAULT_RULE_VERSION` (`"reconciliation-v1"`)** from `domain/reconciliation/matching.py`; 3C passes it explicitly per run.
5. **Idempotency is delegated.** Use-cases call the already-idempotent 3A `add`/`append`; they contain no dedup logic. Storage-level convergence was integration-tested in 3A; this plan only asserts financial-result determinism.
6. **The authenticated `ConnectorPort` is supplied by the caller** (the worker/registration composition root in 3C). Ingestion use-cases receive it as a `run(...)` argument and never build or authenticate it (keeps `application ⊥ infrastructure`).

---

## Dependencies on Plan 3A (must already exist — they do, at HEAD `aeaffbf`)

- Domain ports: `InvoiceRepository`, `UsageEventStore`, `ContractRepository`, `PlanRepository`, `ReconciliationRepository`, `FindingRepository`, `ConnectorPort` (+ `ConnectorCredentials`).
- Domain engine + entities: `reconcile_customer`, `DEFAULT_RULE_VERSION`, `Reconciliation` (with tz-aware `executed_at` + `rule_version`, added in 3A), `Finding`/`FindingLineage`, `Invoice`/`InvoiceLineItem`, `Plan`, `Contract`, `UsageEvent`, `Money`, `TimeWindow`, the id `NewType`s, `RecoveryStatus`, `LeakageType`, `Severity`.
- Domain errors: `InvalidFindingTransitionError` (raised by `Finding.transition_to`).
- The 4th import-linter contract (`application ⊥ infrastructure`) — added in 3A — is what keeps this layer pure.

3B adds **no** new dependency, **no** migration, **no** config, **no** infrastructure.

---

## Interfaces Plan 3C will consume (the public surface this plan produces)

3C (API routers, webhooks, Celery tasks, `run_as_job`) composes these by full module path:

| Symbol | Import path | 3C consumer |
|---|---|---|
| `IngestInvoices(invoices).run(tenant_id, window, connector) -> int` | `yieldfield.application.ingestion.ingest_invoices` | `ingest_invoices` Celery task / webhook re-pull |
| `IngestUsageEvents(usage_events).run(tenant_id, window, connector) -> int` | `yieldfield.application.ingestion.ingest_usage_events` | `ingest_usage_events` task / webhook re-pull |
| `RunReconciliation(invoices, usage_events, contracts, plans, reconciliations, *, finding_id_factory=, clock=).run(tenant_id, window, reconciliation_id, rule_version=) -> Reconciliation` | `yieldfield.application.reconciliation.run_reconciliation` | `run_reconciliation` task (composition root injects concrete repos) |
| `TransitionFinding(findings).run(tenant_id, finding_id, target) -> Finding` | `yieldfield.application.findings.transition_finding` | the four `findings` mutation routes (`review`/`confirm`/`dismiss`/`recover`) |
| `EntityNotFoundError`, `ApplicationError` | `yieldfield.application.errors` | API error handler → 404 (`not_found`) |

**Contracts 3C must honor:** use-cases are constructed with concrete 3A adapters in a composition root (worker task / API dependency), never inside the application layer; the ingestion use-cases receive an **already-authenticated** `ConnectorPort`; `RunReconciliation` callers pre-generate the `reconciliation_id` (so retries reuse it, decision C/E) and may inject a `clock`/`finding_id_factory` for tests but use the defaults in production.

---

## Recommended execution order & verification gates

Execute strictly in order; each task ends green on its own gate before the next begins.

1. **Task 1 — `application/errors.py`** (foundational; `TransitionFinding` depends on it). Gate: `pytest tests/unit/test_application_errors.py` green.
2. **Task 2 — `IngestInvoices`.** Gate: file tests green + `mypy` Success.
3. **Task 3 — `IngestUsageEvents`.** Gate: file tests green + `mypy` Success.
4. **Task 4 — `TransitionFinding`** (depends on Task 1). Gate: file tests green (incl. both error branches) + `mypy` Success.
5. **Task 5 — `RunReconciliation`** (the money path). Gate: 9 file tests green + `mypy` Success.
6. **Task 6 — Full 3B gate.** Gates: `ruff` clean · `black` unchanged · `mypy` Success · `lint-imports` **4 kept, 0 broken** · `pytest tests/unit` **171 passed** · integration unchanged (16 passed, 1 skipped) if Docker is up.

**Definition of done (3B):** all four use-cases + `EntityNotFoundError` implemented test-first, type-clean under `mypy --strict`, lint/format-clean, all four import contracts green (especially `application ⊥ infrastructure`), pure (no framework / no I/O / no infrastructure import), and every component traceable to spec §4. Then **stop and report** — Plan 3C composes this surface into the API, webhooks, and workers.

---

## Self-review notes (author)

- **Spec coverage (Plan 3B row, §15 / §4):** `application/errors.py` (§4.4) → Task 1; `IngestInvoices` (§4.1) → Task 2; `IngestUsageEvents` (§4.1) → Task 3; `TransitionFinding` (§4.3, decision D) → Task 4; `RunReconciliation` orchestration (§4.2, decision C, window/period attribution, per-customer plans, idempotent persist) → Task 5; pure/domain-ports-only + 4th-contract verification (§14) → Task 6. API/webhooks/workers/`run_as_job`/OpenAPI (§5–§7, §10) are **deferred to Plan 3C** by design.
- **Type consistency:** the port method names/signatures used here match 3A exactly — `InvoiceRepository.add`/`list_in_window`, `UsageEventStore.append`/`query`, `ContractRepository.list_for_customer`, `PlanRepository.get`, `ReconciliationRepository.add`, `FindingRepository.get`/`update`, `ConnectorPort.pull_invoices`/`pull_usage_events`, `Finding.transition_to`, `reconcile_customer(... id_factory=, rule_version=)`, `Reconciliation(id, tenant_id, window, currency, executed_at, rule_version, findings)`. Constructor injection (ports positional; `finding_id_factory`/`clock` keyword-only with defaults) mirrors 3A's registration service.
- **No placeholders:** every code/test step carries complete content; commands have expected output; fakes implement the full Protocol surface (mypy-strict-safe) with annotated `def`s.
- **Boundary safety:** no module under `application/` imports `infrastructure`, framework, or performs I/O — the 4th import contract is the machine check (Task 6).
