# Slice 2 — Persistence + Stripe Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the OLTP repositories, the ClickHouse usage-event store, forward-only migrations, and the first billing connector (Stripe), all behind pure domain ports, with tenant scoping enforced at the data layer and the money paths tested hardest.

**Architecture:** Domain defines pure repository/store Protocols beside their aggregates. `infrastructure/persistence/` implements them with sync SQLAlchemy 2.0 + psycopg 3 (separate ORM models + pure mappers — domain stays framework-pure, §6.1). `infrastructure/analytics_store/` implements the usage-event store on ClickHouse. `infrastructure/connectors/base` + `stripe_billing` implement the connector port. Alembic migrations live in `ops/migrations/`. PostgreSQL is the source of truth for tenants/contracts/plans/invoices/reconciliations/findings; ClickHouse is the source of truth for usage events (spec §3).

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 (sync), psycopg 3, Alembic, clickhouse-connect, stripe SDK, pytest + testcontainers + stripe-mock, uv.

**Conventions for every task below:** all `uv run …` / `pytest …` commands run from `backend/`. All `git` commands run from the repo root (`c:\Users\Oton\Documents\yieldfield`) and use repo-root-relative paths. Reference the design spec at `docs/superpowers/specs/2026-05-30-slice-2-persistence-connector-design.md`.

---

## File structure (created/modified in this slice)

```
backend/pyproject.toml                                          # MODIFY: deps, mypy overrides, import-linter, pytest marker
backend/src/yieldfield/domain/billing/repositories.py          # CREATE: Tenant/Plan/Contract/Invoice repo ports
backend/src/yieldfield/domain/billing/usage_event_store.py     # CREATE: UsageEventStore port (OLAP, kept separate)
backend/src/yieldfield/domain/findings/repositories.py         # CREATE: FindingRepository port
backend/src/yieldfield/domain/reconciliation/repositories.py   # CREATE: ReconciliationRepository port
backend/src/yieldfield/infrastructure/persistence/errors.py    # CREATE: PersistenceError
backend/src/yieldfield/infrastructure/persistence/engine.py    # CREATE: engine + sessionmaker factory
backend/src/yieldfield/infrastructure/persistence/models.py    # CREATE: SQLAlchemy declarative ORM rows
backend/src/yieldfield/infrastructure/persistence/metadata.py  # CREATE: Base.metadata for Alembic
backend/src/yieldfield/infrastructure/persistence/mappers.py   # CREATE: pure to_domain/from_domain + precision guard
backend/src/yieldfield/infrastructure/persistence/repositories.py # CREATE: SQLAlchemy repo implementations
backend/src/yieldfield/infrastructure/analytics_store/errors.py    # CREATE: AnalyticsStoreError
backend/src/yieldfield/infrastructure/analytics_store/clickhouse_client.py # CREATE: client factory
backend/src/yieldfield/infrastructure/analytics_store/clickhouse_usage_event_store.py # CREATE: store
backend/src/yieldfield/infrastructure/connectors/base/connector.py # CREATE: BaseConnector ABC + errors
backend/src/yieldfield/infrastructure/connectors/stripe_billing/mapping.py   # CREATE: pure Stripe→domain mappers
backend/src/yieldfield/infrastructure/connectors/stripe_billing/connector.py # CREATE: StripeBillingConnector
backend/tests/unit/test_persistence_ports.py                   # CREATE
backend/tests/unit/test_persistence_engine.py                  # CREATE
backend/tests/unit/test_persistence_models.py                  # CREATE
backend/tests/unit/test_persistence_mappers.py                 # CREATE
backend/tests/unit/test_clickhouse_client.py                   # CREATE
backend/tests/unit/test_stripe_mapping.py                      # CREATE
backend/tests/unit/test_stripe_connector_unit.py               # CREATE
backend/tests/integration/conftest.py                          # CREATE: Docker-gated fixtures
backend/tests/integration/test_oltp_repositories.py            # CREATE
backend/tests/integration/test_clickhouse_store.py             # CREATE
backend/tests/integration/test_stripe_connector_integration.py # CREATE
ops/migrations/alembic.ini                                     # CREATE
ops/migrations/env.py                                          # CREATE
ops/migrations/versions/0001_oltp_schema.py                    # CREATE
ops/migrations/README.md                                       # MODIFY
ops/scripts/bootstrap_clickhouse.py                            # CREATE
.github/workflows/ci.yml                                       # MODIFY: split unit/integration, alembic
```

---

## Task 0: Dependencies + guardrail config

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add runtime + dev dependencies and guardrails to `pyproject.toml`**

In `[project].dependencies`, append:

```toml
    "sqlalchemy>=2.0",
    "psycopg[binary]>=3.2",
    "alembic>=1.14",
    "clickhouse-connect>=0.8",
    "stripe>=11",
```

In `[dependency-groups].dev`, append:

```toml
    "testcontainers>=4.8",
```

In `[tool.pytest.ini_options]`, add a `markers` key (keep existing keys):

```toml
markers = [
    "integration: requires Docker-backed services (Postgres/ClickHouse/stripe-mock); skipped when Docker is unavailable",
]
```

Add mypy overrides (third-party libs without bundled stubs) after the existing `celery.*` override:

```toml
[[tool.mypy.overrides]]
# clickhouse-connect and testcontainers ship without PEP 561 stubs; scope narrowly so
# strictness holds elsewhere. (stripe and alembic ship py.typed — no override needed.)
module = ["clickhouse_connect.*", "testcontainers.*"]
ignore_missing_imports = true
```

In the import-linter domain-purity contract (`forbidden_modules` of "Domain is framework-pure …"), add `"stripe"` to the list (alongside `clickhouse_connect`, `sqlalchemy`, etc.).

- [ ] **Step 2: Lock and sync**

Run: `uv sync`
Expected: resolves and installs sqlalchemy, psycopg, alembic, clickhouse-connect, stripe, testcontainers; `uv.lock` updated.

- [ ] **Step 3: Verify the toolchain still passes on the unchanged tree**

Run: `uv run ruff check . && uv run black --check . && uv run lint-imports && uv run pytest -q`
Expected: all green (106 tests pass; import contracts still kept, now including the `stripe` guard).

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "chore(slice-2): add persistence/connector deps and guardrails (§12/§17)"
```

---

## Task 1: Domain persistence ports (pure Protocols)

Pure `Protocol` interfaces placed beside their aggregates (precedent: `connector_port.py`). Every method that touches tenant-owned data takes `tenant_id` — the tenant-scoping invariant lives in the contract (§11). No framework imports.

**Files:**
- Create: `backend/src/yieldfield/domain/billing/repositories.py`
- Create: `backend/src/yieldfield/domain/billing/usage_event_store.py`
- Create: `backend/src/yieldfield/domain/findings/repositories.py`
- Create: `backend/src/yieldfield/domain/reconciliation/repositories.py`
- Test: `backend/tests/unit/test_persistence_ports.py`

- [ ] **Step 1: Write the failing test**

```python
"""The domain persistence ports are pure, runtime-checkable Protocols (§11, §12)."""

from __future__ import annotations

from typing import get_type_hints

from yieldfield.domain.billing.repositories import (
    ContractRepository,
    InvoiceRepository,
    PlanRepository,
    TenantRepository,
)
from yieldfield.domain.billing.usage_event_store import UsageEventStore
from yieldfield.domain.findings.repositories import FindingRepository
from yieldfield.domain.reconciliation.repositories import ReconciliationRepository


def test_all_read_write_methods_require_tenant_scope() -> None:
    # Every method except TenantRepository.add/get carries an explicit tenant_id arg.
    assert "tenant_id" in get_type_hints(PlanRepository.get)
    assert "tenant_id" in get_type_hints(InvoiceRepository.list_in_window)
    assert "tenant_id" in get_type_hints(UsageEventStore.query)
    assert "tenant_id" in get_type_hints(FindingRepository.list_for_reconciliation)
    assert "tenant_id" in get_type_hints(ReconciliationRepository.add)
    assert "tenant_id" in get_type_hints(ContractRepository.list_for_customer)


def test_a_conforming_stub_satisfies_the_protocol() -> None:
    class _Tenants:
        def add(self, tenant: object) -> None: ...
        def get(self, tenant_id: object) -> object: ...

    assert isinstance(_Tenants(), TenantRepository)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_persistence_ports.py -q`
Expected: FAIL — `ModuleNotFoundError: yieldfield.domain.billing.repositories`.

- [ ] **Step 3: Create `domain/billing/repositories.py`**

```python
"""OLTP repository ports for the billing aggregates (§12). Pure Protocols.

Placed beside their aggregates, mirroring `connector_port.py`. Every tenant-owned
method takes `tenant_id`; there is no cross-tenant accessor (§11). Infrastructure
implements these in `infrastructure/persistence/`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from yieldfield.domain.billing.contract import Contract
from yieldfield.domain.billing.invoice import Invoice
from yieldfield.domain.billing.plan import Plan
from yieldfield.domain.billing.tenant import Tenant
from yieldfield.domain.shared.ids import ContractId, InvoiceId, PlanId, TenantId
from yieldfield.domain.shared.time_window import TimeWindow


@runtime_checkable
class TenantRepository(Protocol):
    def add(self, tenant: Tenant) -> None: ...
    def get(self, tenant_id: TenantId) -> Tenant | None: ...


@runtime_checkable
class PlanRepository(Protocol):
    def add(self, tenant_id: TenantId, plan: Plan) -> None: ...
    def get(self, tenant_id: TenantId, plan_id: PlanId) -> Plan | None: ...
    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Plan]: ...


@runtime_checkable
class ContractRepository(Protocol):
    def add(self, tenant_id: TenantId, contract: Contract) -> None: ...
    def get(self, tenant_id: TenantId, contract_id: ContractId) -> Contract | None: ...
    def list_for_customer(self, tenant_id: TenantId, customer_id: str) -> Sequence[Contract]: ...


@runtime_checkable
class InvoiceRepository(Protocol):
    def add(self, tenant_id: TenantId, invoice: Invoice) -> None: ...
    def get(self, tenant_id: TenantId, invoice_id: InvoiceId) -> Invoice | None: ...
    def list_in_window(self, tenant_id: TenantId, window: TimeWindow) -> Sequence[Invoice]: ...
```

- [ ] **Step 4: Create `domain/billing/usage_event_store.py`**

```python
"""The usage-event store port (§12) — OLAP, kept separate from the OLTP repos.

ClickHouse is the source of truth for usage events (spec §3). Append-mostly, queried
by tenant + time window. Implemented in `infrastructure/analytics_store/`.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.ids import TenantId
from yieldfield.domain.shared.time_window import TimeWindow


@runtime_checkable
class UsageEventStore(Protocol):
    def append(self, tenant_id: TenantId, events: Iterable[UsageEvent]) -> None: ...
    def query(self, tenant_id: TenantId, window: TimeWindow) -> Iterable[UsageEvent]: ...
```

- [ ] **Step 5: Create `domain/findings/repositories.py`**

```python
"""Finding repository port (§12). Findings are created via the Reconciliation
aggregate; this port reads them and persists lifecycle changes (status). Pure Protocol.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from yieldfield.domain.findings.finding import Finding
from yieldfield.domain.shared.ids import FindingId, ReconciliationId, TenantId


@runtime_checkable
class FindingRepository(Protocol):
    def get(self, tenant_id: TenantId, finding_id: FindingId) -> Finding | None: ...
    def list_for_reconciliation(
        self, tenant_id: TenantId, reconciliation_id: ReconciliationId
    ) -> Sequence[Finding]: ...
    def update(self, tenant_id: TenantId, finding: Finding) -> None: ...
```

- [ ] **Step 6: Create `domain/reconciliation/repositories.py`**

```python
"""Reconciliation repository port (§12). The reconciliation is the aggregate root:
persisting it persists its findings; loading it reconstructs them. Pure Protocol.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from yieldfield.domain.reconciliation.reconciliation import Reconciliation
from yieldfield.domain.shared.ids import ReconciliationId, TenantId


@runtime_checkable
class ReconciliationRepository(Protocol):
    def add(self, tenant_id: TenantId, reconciliation: Reconciliation) -> None: ...
    def get(
        self, tenant_id: TenantId, reconciliation_id: ReconciliationId
    ) -> Reconciliation | None: ...
    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Reconciliation]: ...
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_persistence_ports.py -q`
Expected: PASS (2 tests).

- [ ] **Step 8: Verify domain purity still holds**

Run: `uv run lint-imports && uv run mypy`
Expected: import contracts kept; mypy clean.

- [ ] **Step 9: Commit**

```bash
git add backend/src/yieldfield/domain/billing/repositories.py \
  backend/src/yieldfield/domain/billing/usage_event_store.py \
  backend/src/yieldfield/domain/findings/repositories.py \
  backend/src/yieldfield/domain/reconciliation/repositories.py \
  backend/tests/unit/test_persistence_ports.py
git commit -m "feat(domain): persistence + usage-event-store ports (§11/§12)"
```

---

## Task 2: Persistence errors + engine/session factory

**Files:**
- Create: `backend/src/yieldfield/infrastructure/persistence/errors.py`
- Create: `backend/src/yieldfield/infrastructure/persistence/engine.py`
- Test: `backend/tests/unit/test_persistence_engine.py`

- [ ] **Step 1: Write the failing test**

```python
"""Engine factory: psycopg-3 URL normalization + fail-fast on missing config (§16)."""

from __future__ import annotations

import pytest

from yieldfield.infrastructure.persistence.engine import _normalize_url, create_db_engine
from yieldfield.infrastructure.persistence.errors import PersistenceError


def test_normalize_bare_postgresql_url_selects_psycopg3() -> None:
    assert _normalize_url("postgresql://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"


def test_normalize_leaves_explicit_driver_untouched() -> None:
    url = "postgresql+psycopg://u:p@h:5432/db"
    assert _normalize_url(url) == url


def test_create_engine_without_url_fails_fast() -> None:
    with pytest.raises(PersistenceError, match="DATABASE_URL"):
        create_db_engine(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_persistence_engine.py -q`
Expected: FAIL — module `engine`/`errors` not found.

- [ ] **Step 3: Create `infrastructure/persistence/errors.py`**

```python
"""Persistence-layer errors. Infrastructure concern — not a domain error (§6.1)."""

from __future__ import annotations


class PersistenceError(Exception):
    """Raised on a persistence misuse: missing config, tenant mismatch, precision loss."""
```

- [ ] **Step 4: Create `infrastructure/persistence/engine.py`**

```python
"""SQLAlchemy engine + session factory for the OLTP store (§12, §16).

Sync engine (psycopg 3) to match the synchronous connector/worker model. Fails fast
if no database URL is configured, so misconfiguration never surfaces mid money-path.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from yieldfield.infrastructure.persistence.errors import PersistenceError

_BARE_SCHEME = "postgresql://"
_PSYCOPG3_SCHEME = "postgresql+psycopg://"


def _normalize_url(url: str) -> str:
    """Pin the psycopg-3 driver when a bare ``postgresql://`` URL is given."""
    if url.startswith(_BARE_SCHEME):
        return _PSYCOPG3_SCHEME + url[len(_BARE_SCHEME) :]
    return url


def create_db_engine(database_url: str | None) -> Engine:
    """Build the OLTP engine, or fail fast if no URL is configured (§16)."""
    if not database_url:
        raise PersistenceError("DATABASE_URL is required to build the OLTP engine (§16).")
    return create_engine(_normalize_url(database_url), future=True, pool_pre_ping=True)


def build_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    """A session factory; callers own the transaction boundary (application layer, Slice 3)."""
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_persistence_engine.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/src/yieldfield/infrastructure/persistence/errors.py \
  backend/src/yieldfield/infrastructure/persistence/engine.py \
  backend/tests/unit/test_persistence_engine.py
git commit -m "feat(persistence): OLTP engine/session factory with fail-fast config (§16)"
```

---

## Task 3: SQLAlchemy ORM models + metadata

Separate declarative rows (domain stays pure, §6.1). `Money` → `(amount NUMERIC(38,12), currency VARCHAR(3))`; `TimeWindow` → two `TIMESTAMPTZ`; quantities → `NUMERIC(38,12)`; typed IDs → `TEXT`; finding lineage event IDs → `TEXT[]`. Every tenant-owned table has an indexed `tenant_id`.

**Files:**
- Create: `backend/src/yieldfield/infrastructure/persistence/models.py`
- Create: `backend/src/yieldfield/infrastructure/persistence/metadata.py`
- Test: `backend/tests/unit/test_persistence_models.py`

- [ ] **Step 1: Write the failing test**

```python
"""ORM schema shape: tables, tenant indexes, NUMERIC(38,12) money/quantity columns."""

from __future__ import annotations

from sqlalchemy import Numeric

from yieldfield.infrastructure.persistence.metadata import metadata
from yieldfield.infrastructure.persistence.models import MONEY_SCALE


def test_all_oltp_tables_present() -> None:
    assert set(metadata.tables) == {
        "tenants",
        "plans",
        "contracts",
        "invoices",
        "invoice_line_items",
        "reconciliations",
        "findings",
    }


def test_every_tenant_owned_table_has_an_indexed_tenant_id() -> None:
    for name in ("plans", "contracts", "invoices", "invoice_line_items", "reconciliations", "findings"):
        table = metadata.tables[name]
        assert "tenant_id" in table.c
        indexed = {col.name for index in table.indexes for col in index.columns}
        assert "tenant_id" in indexed, f"{name}.tenant_id must be indexed (§12)"


def test_money_columns_are_numeric_38_12() -> None:
    assert MONEY_SCALE == 12
    amount = metadata.tables["findings"].c["amount_amount"].type
    assert isinstance(amount, Numeric)
    assert amount.precision == 38
    assert amount.scale == 12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_persistence_models.py -q`
Expected: FAIL — module `models`/`metadata` not found.

- [ ] **Step 3: Create `infrastructure/persistence/models.py`**

```python
"""SQLAlchemy declarative ORM rows for the OLTP store (§12).

These are infrastructure-only; the domain entities stay framework-pure (§6.1) and are
translated by `mappers.py`. Money/quantity columns are NUMERIC(38,12): exact decimal
(never float, §7), precision 38 to stay aligned with ClickHouse Decimal128(12), scale
12 to cover sub-cent usage-based pricing without rounding at the storage boundary.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime

MONEY_SCALE = 12
_MONEY = Numeric(38, MONEY_SCALE)
_TS = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class TenantRow(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class PlanRow(Base):
    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    unit_price_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    unit_price_currency: Mapped[str] = mapped_column(String(3), nullable=False)


class ContractRow(Base):
    __tablename__ = "contracts"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.id"), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    plan_id: Mapped[str] = mapped_column(Text, ForeignKey("plans.id"), nullable=False)
    term_start: Mapped[datetime] = mapped_column(_TS, nullable=False)
    term_end: Mapped[datetime] = mapped_column(_TS, nullable=False)


class InvoiceRow(Base):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.id"), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[datetime] = mapped_column(_TS, nullable=False)
    period_end: Mapped[datetime] = mapped_column(_TS, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    line_items: Mapped[list[InvoiceLineItemRow]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="InvoiceLineItemRow.id",
    )


class InvoiceLineItemRow(Base):
    __tablename__ = "invoice_line_items"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    invoice_id: Mapped[str] = mapped_column(Text, ForeignKey("invoices.id"), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    amount_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    amount_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    invoice: Mapped[InvoiceRow] = relationship(back_populates="line_items")


class ReconciliationRow(Base):
    __tablename__ = "reconciliations"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.id"), nullable=False, index=True)
    window_start: Mapped[datetime] = mapped_column(_TS, nullable=False)
    window_end: Mapped[datetime] = mapped_column(_TS, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    findings: Mapped[list[FindingRow]] = relationship(
        back_populates="reconciliation",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="FindingRow.id",
    )


class FindingRow(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.id"), nullable=False, index=True)
    reconciliation_id: Mapped[str] = mapped_column(
        Text, ForeignKey("reconciliations.id"), nullable=False, index=True
    )
    customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    leakage_type: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    amount_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    amount_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    lineage_rule_version: Mapped[str] = mapped_column(Text, nullable=False)
    lineage_usage_event_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    lineage_invoice_line_item_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    lineage_model_run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    reconciliation: Mapped[ReconciliationRow] = relationship(back_populates="findings")
```

- [ ] **Step 4: Create `infrastructure/persistence/metadata.py`**

```python
"""Alembic metadata glue (§12). Exposes the declarative metadata for migrations."""

from __future__ import annotations

from sqlalchemy import MetaData

from yieldfield.infrastructure.persistence.models import Base

metadata: MetaData = Base.metadata
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_persistence_models.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Type-check + commit**

Run: `uv run mypy && uv run ruff check . && uv run black --check .`
Expected: clean.

```bash
git add backend/src/yieldfield/infrastructure/persistence/models.py \
  backend/src/yieldfield/infrastructure/persistence/metadata.py \
  backend/tests/unit/test_persistence_models.py
git commit -m "feat(persistence): OLTP ORM models + Alembic metadata (§12)"
```

---

## Task 4: Pure mappers + precision guard (money path)

Pure `to_*`/`*_row` functions translating ORM rows ↔ domain entities. The precision guard (`_storable`) raises `PersistenceError` rather than letting `NUMERIC(38,12)` silently round a value with >12 fractional digits (§7 fail-loud). Heaviest unit coverage — this is a money path.

**Files:**
- Create: `backend/src/yieldfield/infrastructure/persistence/mappers.py`
- Test: `backend/tests/unit/test_persistence_mappers.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Mapper round-trips and the fail-loud precision guard (§7)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from yieldfield.domain.billing.invoice import Invoice, InvoiceLineItem
from yieldfield.domain.billing.plan import Plan
from yieldfield.domain.findings.finding import Finding, FindingLineage
from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.severity import Severity
from yieldfield.domain.reconciliation.reconciliation import Reconciliation
from yieldfield.domain.shared.ids import (
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
from yieldfield.infrastructure.persistence import mappers
from yieldfield.infrastructure.persistence.errors import PersistenceError

_WINDOW = TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))


def test_plan_round_trip_preserves_money() -> None:
    plan = Plan(
        id=PlanId("pl_1"),
        tenant_id=TenantId("t_1"),
        name="API calls",
        metric="api_call",
        unit_price=Money.of("0.0000004", "USD"),
    )
    restored = mappers.to_plan(mappers.plan_row(plan))
    assert restored == plan


def test_invoice_round_trip_preserves_line_items() -> None:
    invoice = Invoice(
        id=InvoiceId("in_1"),
        tenant_id=TenantId("t_1"),
        customer_id="cus_1",
        period=_WINDOW,
        currency="USD",
        line_items=(
            InvoiceLineItem(
                id=InvoiceLineItemId("il_1"),
                metric="api_call",
                quantity=Decimal("1000"),
                amount=Money.of("4.00", "USD"),
            ),
        ),
    )
    restored = mappers.to_invoice(mappers.invoice_row(invoice))
    assert restored == invoice


def test_reconciliation_round_trip_preserves_findings_and_lineage() -> None:
    finding = Finding(
        id=FindingId("fd_1"),
        tenant_id=TenantId("t_1"),
        reconciliation_id=ReconciliationId("rc_1"),
        customer_id="cus_1",
        metric="api_call",
        leakage_type=LeakageType.UNBILLED_USAGE,
        severity=Severity.HIGH,
        amount=Money.of("123.45", "USD"),
        status=RecoveryStatus.NEW,
        lineage=FindingLineage(
            rule_version="reconciliation-v1",
            usage_event_ids=(UsageEventId("ue_1"), UsageEventId("ue_2")),
        ),
        explanation="500 api_call for cus_1 were not billed.",
    )
    recon = Reconciliation(
        id=ReconciliationId("rc_1"),
        tenant_id=TenantId("t_1"),
        window=_WINDOW,
        currency="USD",
        findings=(finding,),
    )
    restored = mappers.to_reconciliation(mappers.reconciliation_row(recon))
    assert restored == recon
    assert restored.findings[0].lineage.usage_event_ids == ("ue_1", "ue_2")


def test_precision_guard_rejects_too_many_fractional_digits() -> None:
    # 13 fractional digits exceeds NUMERIC(38,12): must fail loudly, not round (§7).
    plan = Plan(
        id=PlanId("pl_2"),
        tenant_id=TenantId("t_1"),
        name="too precise",
        metric="m",
        unit_price=Money(Decimal("0.0000000000001"), "USD"),
    )
    with pytest.raises(PersistenceError, match="precision"):
        mappers.plan_row(plan)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_persistence_mappers.py -q`
Expected: FAIL — module `mappers` not found.

- [ ] **Step 3: Create `infrastructure/persistence/mappers.py`**

```python
"""Pure ORM-row ↔ domain-entity mappers (§6.1 keeps the ORM out of the domain).

`_storable` guards the NUMERIC(38,12) boundary: a value with more than 12 fractional
digits would be silently rounded on insert, so we raise instead (§7 fail-loud).
"""

from __future__ import annotations

from decimal import Decimal

from yieldfield.domain.billing.contract import Contract
from yieldfield.domain.billing.invoice import Invoice, InvoiceLineItem
from yieldfield.domain.billing.plan import Plan
from yieldfield.domain.billing.tenant import Tenant
from yieldfield.domain.findings.finding import Finding, FindingLineage
from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.severity import Severity
from yieldfield.domain.reconciliation.reconciliation import Reconciliation
from yieldfield.domain.shared.ids import (
    ContractId,
    FindingId,
    InvoiceId,
    InvoiceLineItemId,
    ModelRunId,
    PlanId,
    ReconciliationId,
    TenantId,
    UsageEventId,
)
from yieldfield.domain.shared.money import Money
from yieldfield.domain.shared.time_window import TimeWindow
from yieldfield.infrastructure.persistence.errors import PersistenceError
from yieldfield.infrastructure.persistence.models import (
    MONEY_SCALE,
    ContractRow,
    FindingRow,
    InvoiceLineItemRow,
    InvoiceRow,
    PlanRow,
    ReconciliationRow,
    TenantRow,
)


def _storable(value: Decimal, field: str) -> Decimal:
    """Reject values that would lose precision at NUMERIC(38,12) (§7)."""
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        raise PersistenceError(f"{field}={value!r} is not a finite decimal.")
    if -exponent > MONEY_SCALE:
        raise PersistenceError(
            f"{field}={value} has more than {MONEY_SCALE} fractional digits and cannot be "
            f"stored without precision loss (§7)."
        )
    return value


# ── Tenant ───────────────────────────────────────────────────────────────────
def tenant_row(tenant: Tenant) -> TenantRow:
    return TenantRow(id=tenant.id, name=tenant.name)


def to_tenant(row: TenantRow) -> Tenant:
    return Tenant(id=TenantId(row.id), name=row.name)


# ── Plan ─────────────────────────────────────────────────────────────────────
def plan_row(plan: Plan) -> PlanRow:
    return PlanRow(
        id=plan.id,
        tenant_id=plan.tenant_id,
        name=plan.name,
        metric=plan.metric,
        unit_price_amount=_storable(plan.unit_price.amount, "unit_price"),
        unit_price_currency=plan.unit_price.currency,
    )


def to_plan(row: PlanRow) -> Plan:
    return Plan(
        id=PlanId(row.id),
        tenant_id=TenantId(row.tenant_id),
        name=row.name,
        metric=row.metric,
        unit_price=Money(row.unit_price_amount, row.unit_price_currency),
    )


# ── Contract ─────────────────────────────────────────────────────────────────
def contract_row(contract: Contract) -> ContractRow:
    return ContractRow(
        id=contract.id,
        tenant_id=contract.tenant_id,
        customer_id=contract.customer_id,
        plan_id=contract.plan_id,
        term_start=contract.term.start,
        term_end=contract.term.end,
    )


def to_contract(row: ContractRow) -> Contract:
    return Contract(
        id=ContractId(row.id),
        tenant_id=TenantId(row.tenant_id),
        customer_id=row.customer_id,
        plan_id=PlanId(row.plan_id),
        term=TimeWindow(row.term_start, row.term_end),
    )


# ── Invoice ──────────────────────────────────────────────────────────────────
def invoice_row(invoice: Invoice) -> InvoiceRow:
    row = InvoiceRow(
        id=invoice.id,
        tenant_id=invoice.tenant_id,
        customer_id=invoice.customer_id,
        period_start=invoice.period.start,
        period_end=invoice.period.end,
        currency=invoice.currency,
    )
    row.line_items = [
        InvoiceLineItemRow(
            id=item.id,
            invoice_id=invoice.id,
            tenant_id=invoice.tenant_id,
            metric=item.metric,
            quantity=_storable(item.quantity, "quantity"),
            amount_amount=_storable(item.amount.amount, "amount"),
            amount_currency=item.amount.currency,
        )
        for item in invoice.line_items
    ]
    return row


def to_invoice(row: InvoiceRow) -> Invoice:
    items = tuple(
        InvoiceLineItem(
            id=InvoiceLineItemId(li.id),
            metric=li.metric,
            quantity=li.quantity,
            amount=Money(li.amount_amount, li.amount_currency),
        )
        for li in row.line_items
    )
    return Invoice(
        id=InvoiceId(row.id),
        tenant_id=TenantId(row.tenant_id),
        customer_id=row.customer_id,
        period=TimeWindow(row.period_start, row.period_end),
        currency=row.currency,
        line_items=items,
    )


# ── Finding / Reconciliation ─────────────────────────────────────────────────
def finding_row(finding: Finding, tenant_id: TenantId) -> FindingRow:
    return FindingRow(
        id=finding.id,
        tenant_id=tenant_id,
        reconciliation_id=finding.reconciliation_id,
        customer_id=finding.customer_id,
        metric=finding.metric,
        leakage_type=finding.leakage_type.value,
        severity=finding.severity.value,
        amount_amount=_storable(finding.amount.amount, "amount"),
        amount_currency=finding.amount.currency,
        status=finding.status.value,
        explanation=finding.explanation,
        lineage_rule_version=finding.lineage.rule_version,
        lineage_usage_event_ids=list(finding.lineage.usage_event_ids),
        lineage_invoice_line_item_id=finding.lineage.invoice_line_item_id,
        lineage_model_run_id=finding.lineage.model_run_id,
    )


def to_finding(row: FindingRow) -> Finding:
    lineage = FindingLineage(
        rule_version=row.lineage_rule_version,
        usage_event_ids=tuple(UsageEventId(x) for x in row.lineage_usage_event_ids),
        invoice_line_item_id=(
            InvoiceLineItemId(row.lineage_invoice_line_item_id)
            if row.lineage_invoice_line_item_id is not None
            else None
        ),
        model_run_id=(
            ModelRunId(row.lineage_model_run_id) if row.lineage_model_run_id is not None else None
        ),
    )
    return Finding(
        id=FindingId(row.id),
        tenant_id=TenantId(row.tenant_id),
        reconciliation_id=ReconciliationId(row.reconciliation_id),
        customer_id=row.customer_id,
        metric=row.metric,
        leakage_type=LeakageType(row.leakage_type),
        severity=Severity(row.severity),
        amount=Money(row.amount_amount, row.amount_currency),
        status=RecoveryStatus(row.status),
        lineage=lineage,
        explanation=row.explanation,
    )


def reconciliation_row(recon: Reconciliation) -> ReconciliationRow:
    row = ReconciliationRow(
        id=recon.id,
        tenant_id=recon.tenant_id,
        window_start=recon.window.start,
        window_end=recon.window.end,
        currency=recon.currency,
    )
    row.findings = [finding_row(f, TenantId(recon.tenant_id)) for f in recon.findings]
    return row


def to_reconciliation(row: ReconciliationRow) -> Reconciliation:
    return Reconciliation(
        id=ReconciliationId(row.id),
        tenant_id=TenantId(row.tenant_id),
        window=TimeWindow(row.window_start, row.window_end),
        currency=row.currency,
        findings=tuple(to_finding(fr) for fr in row.findings),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_persistence_mappers.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Type-check + commit**

Run: `uv run mypy && uv run ruff check . && uv run black --check .`
Expected: clean.

```bash
git add backend/src/yieldfield/infrastructure/persistence/mappers.py \
  backend/tests/unit/test_persistence_mappers.py
git commit -m "feat(persistence): pure ORM<->domain mappers with fail-loud precision guard (§7)"
```

---

## Task 5: SQLAlchemy repository implementations

Implement the domain repo ports. Every query is unconditionally filtered by `tenant_id`; writes guard that the entity's `tenant_id` matches the scope (§11). Full DB behavior is verified in the integration tests (Task 9); here a unit test covers the pre-DB tenant-mismatch guard (no database needed).

**Files:**
- Create: `backend/src/yieldfield/infrastructure/persistence/repositories.py`
- Test: add to `backend/tests/unit/test_persistence_engine.py` (guard is pure; no DB)

- [ ] **Step 1: Write the failing test (append to `test_persistence_engine.py`)**

```python
def test_plan_repo_rejects_tenant_mismatch_before_touching_db() -> None:
    from yieldfield.domain.billing.plan import Plan
    from yieldfield.domain.shared.ids import PlanId, TenantId
    from yieldfield.domain.shared.money import Money
    from yieldfield.infrastructure.persistence.errors import PersistenceError
    from yieldfield.infrastructure.persistence.repositories import SqlAlchemyPlanRepository

    repo = SqlAlchemyPlanRepository(session=None)  # guard runs before any session use
    plan = Plan(
        id=PlanId("pl_1"),
        tenant_id=TenantId("t_OTHER"),
        name="p",
        metric="m",
        unit_price=Money.of("1", "USD"),
    )
    with pytest.raises(PersistenceError, match="does not match"):
        repo.add(TenantId("t_1"), plan)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_persistence_engine.py::test_plan_repo_rejects_tenant_mismatch_before_touching_db -q`
Expected: FAIL — module `repositories` not found.

- [ ] **Step 3: Create `infrastructure/persistence/repositories.py`**

```python
"""SQLAlchemy implementations of the domain repository ports (§12).

Tenant scoping (§11) is enforced here: every read filters by `tenant_id`, and every
write guards that the entity's `tenant_id` matches the caller's scope. Sessions are
injected; the caller owns the transaction boundary (application layer, Slice 3).
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from yieldfield.domain.billing.contract import Contract
from yieldfield.domain.billing.invoice import Invoice
from yieldfield.domain.billing.plan import Plan
from yieldfield.domain.billing.tenant import Tenant
from yieldfield.domain.findings.finding import Finding
from yieldfield.domain.reconciliation.reconciliation import Reconciliation
from yieldfield.domain.shared.ids import (
    ContractId,
    FindingId,
    InvoiceId,
    PlanId,
    ReconciliationId,
    TenantId,
)
from yieldfield.domain.shared.time_window import TimeWindow
from yieldfield.infrastructure.persistence import mappers
from yieldfield.infrastructure.persistence.errors import PersistenceError
from yieldfield.infrastructure.persistence.models import (
    ContractRow,
    FindingRow,
    InvoiceRow,
    PlanRow,
    ReconciliationRow,
    TenantRow,
)


def _guard(scope: TenantId, entity_tenant: str) -> None:
    if str(scope) != str(entity_tenant):
        raise PersistenceError(
            f"entity tenant_id {entity_tenant!r} does not match scope {scope!r} (§11)."
        )


class SqlAlchemyTenantRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, tenant: Tenant) -> None:
        self._session.add(mappers.tenant_row(tenant))

    def get(self, tenant_id: TenantId) -> Tenant | None:
        row = self._session.get(TenantRow, str(tenant_id))
        return mappers.to_tenant(row) if row is not None else None


class SqlAlchemyPlanRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, tenant_id: TenantId, plan: Plan) -> None:
        _guard(tenant_id, plan.tenant_id)
        self._session.add(mappers.plan_row(plan))

    def get(self, tenant_id: TenantId, plan_id: PlanId) -> Plan | None:
        row = self._session.scalars(
            select(PlanRow).where(PlanRow.id == str(plan_id), PlanRow.tenant_id == str(tenant_id))
        ).first()
        return mappers.to_plan(row) if row is not None else None

    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Plan]:
        rows = self._session.scalars(
            select(PlanRow).where(PlanRow.tenant_id == str(tenant_id)).order_by(PlanRow.id)
        ).all()
        return [mappers.to_plan(r) for r in rows]


class SqlAlchemyContractRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, tenant_id: TenantId, contract: Contract) -> None:
        _guard(tenant_id, contract.tenant_id)
        self._session.add(mappers.contract_row(contract))

    def get(self, tenant_id: TenantId, contract_id: ContractId) -> Contract | None:
        row = self._session.scalars(
            select(ContractRow).where(
                ContractRow.id == str(contract_id), ContractRow.tenant_id == str(tenant_id)
            )
        ).first()
        return mappers.to_contract(row) if row is not None else None

    def list_for_customer(self, tenant_id: TenantId, customer_id: str) -> Sequence[Contract]:
        rows = self._session.scalars(
            select(ContractRow)
            .where(ContractRow.tenant_id == str(tenant_id), ContractRow.customer_id == customer_id)
            .order_by(ContractRow.id)
        ).all()
        return [mappers.to_contract(r) for r in rows]


class SqlAlchemyInvoiceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, tenant_id: TenantId, invoice: Invoice) -> None:
        _guard(tenant_id, invoice.tenant_id)
        self._session.add(mappers.invoice_row(invoice))

    def get(self, tenant_id: TenantId, invoice_id: InvoiceId) -> Invoice | None:
        row = self._session.scalars(
            select(InvoiceRow).where(
                InvoiceRow.id == str(invoice_id), InvoiceRow.tenant_id == str(tenant_id)
            )
        ).first()
        return mappers.to_invoice(row) if row is not None else None

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


class SqlAlchemyReconciliationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, tenant_id: TenantId, reconciliation: Reconciliation) -> None:
        _guard(tenant_id, reconciliation.tenant_id)
        self._session.add(mappers.reconciliation_row(reconciliation))

    def get(
        self, tenant_id: TenantId, reconciliation_id: ReconciliationId
    ) -> Reconciliation | None:
        row = self._session.scalars(
            select(ReconciliationRow).where(
                ReconciliationRow.id == str(reconciliation_id),
                ReconciliationRow.tenant_id == str(tenant_id),
            )
        ).first()
        return mappers.to_reconciliation(row) if row is not None else None

    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Reconciliation]:
        rows = self._session.scalars(
            select(ReconciliationRow)
            .where(ReconciliationRow.tenant_id == str(tenant_id))
            .order_by(ReconciliationRow.id)
        ).all()
        return [mappers.to_reconciliation(r) for r in rows]


class SqlAlchemyFindingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, tenant_id: TenantId, finding_id: FindingId) -> Finding | None:
        row = self._session.scalars(
            select(FindingRow).where(
                FindingRow.id == str(finding_id), FindingRow.tenant_id == str(tenant_id)
            )
        ).first()
        return mappers.to_finding(row) if row is not None else None

    def list_for_reconciliation(
        self, tenant_id: TenantId, reconciliation_id: ReconciliationId
    ) -> Sequence[Finding]:
        rows = self._session.scalars(
            select(FindingRow)
            .where(
                FindingRow.tenant_id == str(tenant_id),
                FindingRow.reconciliation_id == str(reconciliation_id),
            )
            .order_by(FindingRow.id)
        ).all()
        return [mappers.to_finding(r) for r in rows]

    def update(self, tenant_id: TenantId, finding: Finding) -> None:
        _guard(tenant_id, finding.tenant_id)
        row = self._session.scalars(
            select(FindingRow).where(
                FindingRow.id == str(finding.id), FindingRow.tenant_id == str(tenant_id)
            )
        ).first()
        if row is None:
            raise PersistenceError(f"Finding {finding.id!r} not found for tenant {tenant_id!r}.")
        row.status = finding.status.value
        row.severity = finding.severity.value
        row.amount_amount = mappers._storable(finding.amount.amount, "amount")
        row.amount_currency = finding.amount.currency
        row.explanation = finding.explanation
```

> Note: `mappers._storable` is reused intentionally — the precision guard is the single
> source of truth for the storage boundary. If preferred during implementation, promote it to
> a public `mappers.storable`; keep one definition either way (DRY).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_persistence_engine.py -q`
Expected: PASS (now 4 tests incl. the tenant-mismatch guard).

- [ ] **Step 5: Type-check + commit**

Run: `uv run mypy && uv run ruff check . && uv run black --check .`
Expected: clean. (If ruff flags `mappers._storable` private access, promote it to `mappers.storable` and update both call sites.)

```bash
git add backend/src/yieldfield/infrastructure/persistence/repositories.py \
  backend/tests/unit/test_persistence_engine.py
git commit -m "feat(persistence): tenant-scoped SQLAlchemy repositories (§11/§12)"
```

---

## Task 6: Alembic — config, env, initial forward-only migration

Migrations live in `ops/migrations/` (ARCHITECTURE). `env.py` imports `metadata` from the persistence package; the initial migration is hand-authored to match the models. Applying it is verified end-to-end in Task 9.

**Files:**
- Create: `ops/migrations/alembic.ini`
- Create: `ops/migrations/env.py`
- Create: `ops/migrations/versions/0001_oltp_schema.py`
- Modify: `ops/migrations/README.md`

- [ ] **Step 1: Create `ops/migrations/alembic.ini`**

```ini
# Alembic config for the Yieldfield OLTP schema (§12). The URL is supplied at runtime
# (YIELDFIELD_DATABASE_URL env var, or set_main_option in tests/CI) — never committed.
[alembic]
script_location = %(here)s
prepend_sys_path = .
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

- [ ] **Step 2: Create `ops/migrations/env.py`**

```python
"""Alembic environment for the OLTP schema (§12).

Resolves the database URL from Alembic config (set by tests/CI) or the
YIELDFIELD_DATABASE_URL env var, normalizing to the psycopg-3 driver. Target metadata
comes from the persistence package, so migrations track the ORM models.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine

from yieldfield.infrastructure.persistence.engine import _normalize_url
from yieldfield.infrastructure.persistence.metadata import metadata

config = context.config
target_metadata = metadata


def _resolve_url() -> str:
    url = config.get_main_option("sqlalchemy.url") or os.environ.get("YIELDFIELD_DATABASE_URL")
    if not url:
        raise RuntimeError("No database URL: set sqlalchemy.url or YIELDFIELD_DATABASE_URL.")
    return _normalize_url(url)


def run_migrations_online() -> None:
    engine = create_engine(_resolve_url(), future=True)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():  # pragma: no cover - online mode only in this project
    raise RuntimeError("Offline migrations are not supported; provide a database URL.")
run_migrations_online()
```

- [ ] **Step 3: Create `ops/migrations/versions/0001_oltp_schema.py`**

```python
"""Initial OLTP schema (tenants, plans, contracts, invoices, line items, reconciliations, findings).

Forward-only (§12). Money/quantity columns are NUMERIC(38,12); usage events live in
ClickHouse (spec §3), so finding lineage event IDs are a TEXT[] array, not an FK.

Revision ID: 0001_oltp_schema
Revises:
Create Date: 2026-05-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_oltp_schema"
down_revision = None
branch_labels = None
depends_on = None

_MONEY = sa.Numeric(precision=38, scale=12)
_CCY = sa.String(length=3)
_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
    )
    op.create_table(
        "plans",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("unit_price_amount", _MONEY, nullable=False),
        sa.Column("unit_price_currency", _CCY, nullable=False),
    )
    op.create_index("ix_plans_tenant_id", "plans", ["tenant_id"])
    op.create_table(
        "contracts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("plan_id", sa.Text(), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("term_start", _TS, nullable=False),
        sa.Column("term_end", _TS, nullable=False),
    )
    op.create_index("ix_contracts_tenant_id", "contracts", ["tenant_id"])
    op.create_table(
        "invoices",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("period_start", _TS, nullable=False),
        sa.Column("period_end", _TS, nullable=False),
        sa.Column("currency", _CCY, nullable=False),
    )
    op.create_index("ix_invoices_tenant_id", "invoices", ["tenant_id"])
    op.create_table(
        "invoice_line_items",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("invoice_id", sa.Text(), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("quantity", _MONEY, nullable=False),
        sa.Column("amount_amount", _MONEY, nullable=False),
        sa.Column("amount_currency", _CCY, nullable=False),
    )
    op.create_index("ix_invoice_line_items_invoice_id", "invoice_line_items", ["invoice_id"])
    op.create_index("ix_invoice_line_items_tenant_id", "invoice_line_items", ["tenant_id"])
    op.create_table(
        "reconciliations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("window_start", _TS, nullable=False),
        sa.Column("window_end", _TS, nullable=False),
        sa.Column("currency", _CCY, nullable=False),
    )
    op.create_index("ix_reconciliations_tenant_id", "reconciliations", ["tenant_id"])
    op.create_table(
        "findings",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "reconciliation_id", sa.Text(), sa.ForeignKey("reconciliations.id"), nullable=False
        ),
        sa.Column("customer_id", sa.Text(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("leakage_type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("amount_amount", _MONEY, nullable=False),
        sa.Column("amount_currency", _CCY, nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("lineage_rule_version", sa.Text(), nullable=False),
        sa.Column(
            "lineage_usage_event_ids",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("lineage_invoice_line_item_id", sa.Text(), nullable=True),
        sa.Column("lineage_model_run_id", sa.Text(), nullable=True),
    )
    op.create_index("ix_findings_tenant_id", "findings", ["tenant_id"])
    op.create_index("ix_findings_reconciliation_id", "findings", ["reconciliation_id"])


def downgrade() -> None:
    op.drop_table("findings")
    op.drop_table("reconciliations")
    op.drop_table("invoice_line_items")
    op.drop_table("invoices")
    op.drop_table("contracts")
    op.drop_table("plans")
    op.drop_table("tenants")
```

- [ ] **Step 4: Update `ops/migrations/README.md`**

```markdown
# migrations/

Forward-only, reviewed-like-code Alembic migrations for the PostgreSQL OLTP schema (§12).

- Config: `alembic.ini`; environment: `env.py` (imports `metadata` from
  `yieldfield.infrastructure.persistence`).
- The database URL is supplied at runtime via `YIELDFIELD_DATABASE_URL` (or Alembic's
  `sqlalchemy.url` in CI/tests) — never committed (§16).

Apply (from `backend/`, where the `yieldfield` package is installed):

    uv run alembic -c ../ops/migrations/alembic.ini upgrade head

ClickHouse (OLAP) schema is **not** Alembic-managed; it is provisioned by the usage-event
store's `ensure_schema()` and `ops/scripts/bootstrap_clickhouse.py` (spec §6).
```

- [ ] **Step 5: Smoke-check that the migration module imports and the revision is wired**

Run: `uv run python -c "import importlib.util, pathlib; p=pathlib.Path('../ops/migrations/versions/0001_oltp_schema.py'); s=importlib.util.spec_from_file_location('m', p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.revision, m.down_revision)"`
Expected: prints `0001_oltp_schema None`.

- [ ] **Step 6: Commit**

```bash
git add ops/migrations/alembic.ini ops/migrations/env.py \
  ops/migrations/versions/0001_oltp_schema.py ops/migrations/README.md
git commit -m "feat(migrations): forward-only Alembic OLTP schema (§12)"
```

---

## Task 7: ClickHouse usage-event store

Implements `UsageEventStore` on ClickHouse: `usage_events` partitioned by `(tenant_id, toYYYYMM(occurred_at))`, `quantity Decimal128(12)`. Append/query are tenant-scoped; the window is half-open. `ensure_schema()` provisions the table (ClickHouse is not Alembic-managed). Full behavior verified in Task 10; here a unit test covers URL parsing + the append tenant guard.

**Files:**
- Create: `backend/src/yieldfield/infrastructure/analytics_store/errors.py`
- Create: `backend/src/yieldfield/infrastructure/analytics_store/clickhouse_client.py`
- Create: `backend/src/yieldfield/infrastructure/analytics_store/clickhouse_usage_event_store.py`
- Test: `backend/tests/unit/test_clickhouse_client.py`

- [ ] **Step 1: Write the failing test**

```python
"""ClickHouse client URL parsing + the append tenant-scope guard (no Docker)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.ids import TenantId, UsageEventId
from yieldfield.infrastructure.analytics_store.clickhouse_client import parse_clickhouse_url
from yieldfield.infrastructure.analytics_store.clickhouse_usage_event_store import (
    ClickHouseUsageEventStore,
)
from yieldfield.infrastructure.analytics_store.errors import AnalyticsStoreError


def test_parse_clickhouse_url_extracts_connection_parts() -> None:
    parts = parse_clickhouse_url("http://user:pass@host:8123/analytics")
    assert parts == {
        "host": "host",
        "port": 8123,
        "username": "user",
        "password": "pass",
        "database": "analytics",
        "secure": False,
    }


def test_parse_clickhouse_url_requires_a_value() -> None:
    with pytest.raises(AnalyticsStoreError, match="CLICKHOUSE_URL"):
        parse_clickhouse_url(None)


def test_append_rejects_events_from_another_tenant() -> None:
    store = ClickHouseUsageEventStore(client=None)  # guard runs before client use
    foreign = UsageEvent(
        id=UsageEventId("ue_1"),
        tenant_id=TenantId("t_OTHER"),
        customer_id="cus_1",
        metric="api_call",
        quantity=Decimal("1"),
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(AnalyticsStoreError, match="does not match"):
        store.append(TenantId("t_1"), [foreign])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_clickhouse_client.py -q`
Expected: FAIL — modules not found.

- [ ] **Step 3: Create `infrastructure/analytics_store/errors.py`**

```python
"""Analytics-store (OLAP) errors. Infrastructure concern, not a domain error (§6.1)."""

from __future__ import annotations


class AnalyticsStoreError(Exception):
    """Raised on an OLAP misuse: missing config or tenant-scope violation."""
```

- [ ] **Step 4: Create `infrastructure/analytics_store/clickhouse_client.py`**

```python
"""ClickHouse client factory (§12). Parses the configured URL and builds a client.

URL form: ``http(s)://user:pass@host:port/database`` (matches docker-compose / .env).
"""

from __future__ import annotations

from typing import Any, TypedDict
from urllib.parse import urlsplit

from yieldfield.infrastructure.analytics_store.errors import AnalyticsStoreError

_DEFAULT_HTTP_PORT = 8123


class ClickHouseParts(TypedDict):
    host: str
    port: int
    username: str
    password: str
    database: str
    secure: bool


def parse_clickhouse_url(url: str | None) -> ClickHouseParts:
    if not url:
        raise AnalyticsStoreError("CLICKHOUSE_URL is required to build the analytics client (§16).")
    parts = urlsplit(url)
    database = parts.path.lstrip("/") or "default"
    return ClickHouseParts(
        host=parts.hostname or "localhost",
        port=parts.port or _DEFAULT_HTTP_PORT,
        username=parts.username or "default",
        password=parts.password or "",
        database=database,
        secure=parts.scheme == "https",
    )


def create_clickhouse_client(url: str | None) -> Any:
    """Build a clickhouse-connect client from the configured URL (fail-fast, §16)."""
    import clickhouse_connect

    parts = parse_clickhouse_url(url)
    return clickhouse_connect.get_client(
        host=parts["host"],
        port=parts["port"],
        username=parts["username"],
        password=parts["password"],
        database=parts["database"],
        secure=parts["secure"],
    )
```

- [ ] **Step 5: Create `infrastructure/analytics_store/clickhouse_usage_event_store.py`**

```python
"""ClickHouse implementation of the UsageEventStore port (§12, §13).

ClickHouse is the source of truth for usage events (spec §3): high-volume, append-mostly,
partitioned by (tenant_id, month) for tenant+time scans. Append/query are tenant-scoped;
the window is half-open [start, end) to match TimeWindow.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.ids import TenantId, UsageEventId
from yieldfield.domain.shared.time_window import TimeWindow
from yieldfield.infrastructure.analytics_store.errors import AnalyticsStoreError

_TABLE = "usage_events"
_COLUMNS = ["id", "tenant_id", "customer_id", "metric", "quantity", "occurred_at"]

_DDL = f"""
CREATE TABLE IF NOT EXISTS {_TABLE} (
    id String,
    tenant_id String,
    customer_id String,
    metric String,
    quantity Decimal128(12),
    occurred_at DateTime64(6, 'UTC')
)
ENGINE = MergeTree
PARTITION BY (tenant_id, toYYYYMM(occurred_at))
ORDER BY (tenant_id, occurred_at, id)
"""


def _as_utc_naive(moment: datetime) -> datetime:
    """ClickHouse DateTime64('UTC') binds best with UTC-normalized naive datetimes."""
    return moment.astimezone(UTC).replace(tzinfo=None)


class ClickHouseUsageEventStore:
    def __init__(self, client: Any, *, table: str = _TABLE) -> None:
        self._client = client
        self._table = table

    def ensure_schema(self) -> None:
        self._client.command(_DDL.replace(_TABLE, self._table))

    def append(self, tenant_id: TenantId, events: Iterable[UsageEvent]) -> None:
        rows = []
        for event in events:
            if str(event.tenant_id) != str(tenant_id):
                raise AnalyticsStoreError(
                    f"event tenant_id {event.tenant_id!r} does not match scope {tenant_id!r} (§11)."
                )
            rows.append(
                [
                    str(event.id),
                    str(event.tenant_id),
                    event.customer_id,
                    event.metric,
                    event.quantity,
                    _as_utc_naive(event.occurred_at),
                ]
            )
        if rows:
            self._client.insert(self._table, rows, column_names=_COLUMNS)

    def query(self, tenant_id: TenantId, window: TimeWindow) -> Iterable[UsageEvent]:
        result = self._client.query(
            f"SELECT {', '.join(_COLUMNS)} FROM {self._table} "
            "WHERE tenant_id = {tid:String} "
            "AND occurred_at >= {start:DateTime64} AND occurred_at < {end:DateTime64} "
            "ORDER BY occurred_at, id",
            parameters={
                "tid": str(tenant_id),
                "start": _as_utc_naive(window.start),
                "end": _as_utc_naive(window.end),
            },
        )
        return [self._to_event(row) for row in result.result_rows]

    @staticmethod
    def _to_event(row: tuple[Any, ...]) -> UsageEvent:
        occurred_at = row[5]
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        return UsageEvent(
            id=UsageEventId(str(row[0])),
            tenant_id=TenantId(str(row[1])),
            customer_id=str(row[2]),
            metric=str(row[3]),
            quantity=Decimal(str(row[4])),
            occurred_at=occurred_at,
        )
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_clickhouse_client.py -q`
Expected: PASS (3 tests).

- [ ] **Step 7: Type-check + commit**

Run: `uv run mypy && uv run ruff check . && uv run black --check .`
Expected: clean.

```bash
git add backend/src/yieldfield/infrastructure/analytics_store/errors.py \
  backend/src/yieldfield/infrastructure/analytics_store/clickhouse_client.py \
  backend/src/yieldfield/infrastructure/analytics_store/clickhouse_usage_event_store.py \
  backend/tests/unit/test_clickhouse_client.py
git commit -m "feat(analytics): ClickHouse usage-event store, tenant-scoped (§11/§12/§13)"
```

---

## Task 8: Stripe connector (base ABC + pure mappers + connector)

The connector port's first concrete implementation (§17). Pure Stripe→domain mappers carry the money-path correctness and are unit-tested directly; the connector methods are thin Stripe calls that delegate to the mappers. Webhook verification is a deterministic, network-free unit test.

**Files:**
- Create: `backend/src/yieldfield/infrastructure/connectors/base/connector.py`
- Create: `backend/src/yieldfield/infrastructure/connectors/stripe_billing/mapping.py`
- Create: `backend/src/yieldfield/infrastructure/connectors/stripe_billing/connector.py`
- Test: `backend/tests/unit/test_stripe_mapping.py`
- Test: `backend/tests/unit/test_stripe_connector_unit.py`

### 8a — Base connector

- [ ] **Step 1: Create `infrastructure/connectors/base/connector.py`**

```python
"""Abstract base connector + shared utilities (§17).

Concrete connectors (Stripe, Metronome, …) subclass this and structurally satisfy the
domain `ConnectorPort`. Shared helpers: required-secret access that never logs the value
(§11), and a webhook timestamp tolerance constant (replay safety, §11).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from yieldfield.domain.billing.connector_port import ConnectorCredentials
from yieldfield.domain.billing.invoice import Invoice
from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.time_window import TimeWindow

WEBHOOK_TOLERANCE_SECONDS = 300


class ConnectorError(Exception):
    """Base error for connector failures."""


class ConnectorAuthError(ConnectorError):
    """Raised when credentials are missing or invalid (§11). Never includes the secret."""


class BaseConnector(ABC):
    """Abstract base every billing connector extends (§17)."""

    @abstractmethod
    def authenticate(self, credentials: ConnectorCredentials) -> None: ...

    @abstractmethod
    def pull_usage_events(self, window: TimeWindow) -> Iterable[UsageEvent]: ...

    @abstractmethod
    def pull_invoices(self, window: TimeWindow) -> Iterable[Invoice]: ...

    @abstractmethod
    def verify_webhook(self, payload: bytes, signature: str) -> bool: ...

    @staticmethod
    def _require_secret(credentials: ConnectorCredentials, key: str) -> str:
        try:
            return credentials.secrets[key]
        except KeyError as exc:
            raise ConnectorAuthError(f"Missing required credential: {key!r}.") from exc
```

### 8b — Pure mappers

- [ ] **Step 2: Write the failing mapper tests (`test_stripe_mapping.py`)**

```python
"""Pure Stripe→domain mappers — the connector money path (currency, minor units, tz)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from yieldfield.domain.shared.ids import TenantId
from yieldfield.domain.shared.money import Money
from yieldfield.infrastructure.connectors.stripe_billing.mapping import (
    invoice_from_stripe,
    usage_event_from_stripe,
)


def test_invoice_maps_currency_minor_units_and_timestamps() -> None:
    raw = {
        "id": "in_1",
        "customer": "cus_1",
        "period_start": 1735689600,  # 2025-01-01T00:00:00Z
        "period_end": 1738368000,  # 2025-02-01T00:00:00Z
        "currency": "usd",
        "lines": [
            {"id": "il_1", "metric": "api_call", "quantity": 1000, "amount": 400, "currency": "usd"},
        ],
    }
    invoice = invoice_from_stripe(TenantId("t_1"), raw)
    assert invoice.tenant_id == "t_1"
    assert invoice.currency == "USD"
    assert invoice.period.start == datetime(2025, 1, 1, tzinfo=UTC)
    assert invoice.line_items[0].amount == Money.of("4.00", "USD")  # 400 cents → 4.00
    assert invoice.line_items[0].quantity == Decimal("1000")


def test_usage_event_maps_quantity_and_timestamp() -> None:
    raw = {
        "id": "ue_1",
        "customer_id": "cus_1",
        "metric": "api_call",
        "quantity": 12,
        "occurred_at": 1735689600,
    }
    event = usage_event_from_stripe(TenantId("t_1"), raw)
    assert event.tenant_id == "t_1"
    assert event.quantity == Decimal("12")
    assert event.occurred_at == datetime(2025, 1, 1, tzinfo=UTC)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_stripe_mapping.py -q`
Expected: FAIL — module `mapping` not found.

- [ ] **Step 4: Create `infrastructure/connectors/stripe_billing/mapping.py`**

```python
"""Pure translation of Stripe objects → domain entities (§17).

Kept pure and unit-tested so the money path is correct regardless of how Stripe is
reached. Inputs are Mapping-like (Stripe SDK objects are dict-like; tests pass dicts).
Stripe currencies are lowercase and amounts are in minor units; we uppercase and convert
to major units (two-decimal assumption — zero-decimal currencies are a later refinement).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from yieldfield.domain.billing.invoice import Invoice, InvoiceLineItem
from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.ids import InvoiceId, InvoiceLineItemId, TenantId, UsageEventId
from yieldfield.domain.shared.money import Money
from yieldfield.domain.shared.time_window import TimeWindow

_MINOR_UNITS = Decimal(100)


def _ts(value: Any) -> datetime:
    return datetime.fromtimestamp(int(value), tz=UTC)


def _money_from_minor(amount: Any, currency: str) -> Money:
    return Money(Decimal(int(amount)) / _MINOR_UNITS, currency.upper())


def invoice_from_stripe(tenant_id: TenantId, raw: Mapping[str, Any]) -> Invoice:
    currency = str(raw["currency"]).upper()
    line_items = tuple(
        InvoiceLineItem(
            id=InvoiceLineItemId(str(line["id"])),
            metric=str(line["metric"]),
            quantity=Decimal(str(line.get("quantity") or 0)),
            amount=_money_from_minor(line["amount"], str(line["currency"])),
        )
        for line in raw["lines"]
    )
    return Invoice(
        id=InvoiceId(str(raw["id"])),
        tenant_id=tenant_id,
        customer_id=str(raw["customer"]),
        period=TimeWindow(_ts(raw["period_start"]), _ts(raw["period_end"])),
        currency=currency,
        line_items=line_items,
    )


def usage_event_from_stripe(tenant_id: TenantId, raw: Mapping[str, Any]) -> UsageEvent:
    return UsageEvent(
        id=UsageEventId(str(raw["id"])),
        tenant_id=tenant_id,
        customer_id=str(raw["customer_id"]),
        metric=str(raw["metric"]),
        quantity=Decimal(str(raw["quantity"])),
        occurred_at=_ts(raw["occurred_at"]),
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_stripe_mapping.py -q`
Expected: PASS (2 tests).

### 8c — Connector

- [ ] **Step 6: Write the failing connector unit tests (`test_stripe_connector_unit.py`)**

```python
"""Connector unit tests: port conformance, missing-credential failure, webhook verify."""

from __future__ import annotations

import hashlib
import hmac
import time

import pytest

from yieldfield.domain.billing.connector_port import ConnectorCredentials, ConnectorPort
from yieldfield.domain.shared.ids import TenantId
from yieldfield.infrastructure.connectors.base.connector import ConnectorAuthError
from yieldfield.infrastructure.connectors.stripe_billing.connector import StripeBillingConnector

_SECRET = "whsec_test"


def _sign(payload: bytes, secret: str, timestamp: int) -> str:
    signed = f"{timestamp}.{payload.decode()}".encode()
    digest = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def _authed() -> StripeBillingConnector:
    c = StripeBillingConnector(TenantId("t_1"))
    c.authenticate(ConnectorCredentials(secrets={"api_key": "sk_test_x", "webhook_secret": _SECRET}))
    return c


def test_connector_satisfies_the_domain_port() -> None:
    assert isinstance(StripeBillingConnector(TenantId("t_1")), ConnectorPort)


def test_authenticate_requires_api_key() -> None:
    c = StripeBillingConnector(TenantId("t_1"))
    with pytest.raises(ConnectorAuthError, match="api_key"):
        c.authenticate(ConnectorCredentials(secrets={}))


def test_verify_webhook_accepts_a_valid_signature() -> None:
    payload = b'{"id":"evt_1","type":"invoice.created"}'
    header = _sign(payload, _SECRET, int(time.time()))
    assert _authed().verify_webhook(payload, header) is True


def test_verify_webhook_rejects_a_tampered_payload() -> None:
    payload = b'{"id":"evt_1","type":"invoice.created"}'
    header = _sign(payload, _SECRET, int(time.time()))
    assert _authed().verify_webhook(b'{"id":"evil"}', header) is False


def test_verify_webhook_rejects_a_stale_timestamp() -> None:
    payload = b'{"id":"evt_1"}'
    header = _sign(payload, _SECRET, int(time.time()) - 10_000)  # outside tolerance
    assert _authed().verify_webhook(payload, header) is False
```

- [ ] **Step 7: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_stripe_connector_unit.py -q`
Expected: FAIL — module `connector` not found.

- [ ] **Step 8: Create `infrastructure/connectors/stripe_billing/connector.py`**

```python
"""Stripe Billing connector — first concrete ConnectorPort implementation (§4 CORE, §17).

Per-tenant: `tenant_id` stamps every pulled entity. Uses the official `stripe` SDK via
its resource API with a per-call api_key (version-stable). Stripe's usage read surface is
evolving (usage records → meter events); usage is read here from subscription-item usage
record summaries and isolated behind the pure mapper, so the source can change without
touching reconciliation (§17). Invoices are the primary, well-supported pull.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import stripe

from yieldfield.domain.billing.connector_port import ConnectorCredentials
from yieldfield.domain.billing.invoice import Invoice
from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.ids import TenantId
from yieldfield.domain.shared.time_window import TimeWindow
from yieldfield.infrastructure.connectors.base.connector import (
    WEBHOOK_TOLERANCE_SECONDS,
    BaseConnector,
    ConnectorAuthError,
)

_API_KEY = "api_key"
_WEBHOOK_SECRET = "webhook_secret"
_PAGE_LIMIT = 100


class StripeBillingConnector(BaseConnector):
    def __init__(self, tenant_id: TenantId) -> None:
        self._tenant_id = tenant_id
        self._api_key: str | None = None
        self._webhook_secret: str | None = None

    def authenticate(self, credentials: ConnectorCredentials) -> None:
        self._api_key = self._require_secret(credentials, _API_KEY)
        self._webhook_secret = credentials.secrets.get(_WEBHOOK_SECRET)

    def _key(self) -> str:
        if not self._api_key:
            raise ConnectorAuthError("Not authenticated; call authenticate() first.")
        return self._api_key

    def pull_invoices(self, window: TimeWindow) -> Iterable[Invoice]:
        from yieldfield.infrastructure.connectors.stripe_billing.mapping import invoice_from_stripe

        params = {
            "created": {
                "gte": int(window.start.timestamp()),
                "lt": int(window.end.timestamp()),
            },
            "limit": _PAGE_LIMIT,
            "expand": ["data.lines"],
        }
        for inv in stripe.Invoice.list(api_key=self._key(), **params).auto_paging_iter():
            raw = {
                "id": inv["id"],
                "customer": inv["customer"],
                "period_start": inv["period_start"],
                "period_end": inv["period_end"],
                "currency": inv["currency"],
                "lines": [
                    {
                        "id": line["id"],
                        "metric": self._line_metric(line),
                        "quantity": line.get("quantity") or 0,
                        "amount": line["amount"],
                        "currency": line["currency"],
                    }
                    for line in inv["lines"]["data"]
                ],
            }
            yield invoice_from_stripe(self._tenant_id, raw)

    def pull_usage_events(self, window: TimeWindow) -> Iterable[UsageEvent]:
        from yieldfield.infrastructure.connectors.stripe_billing.mapping import (
            usage_event_from_stripe,
        )

        key = self._key()
        fallback_start = int(window.start.timestamp())
        for sub in stripe.Subscription.list(
            api_key=key, status="all", limit=_PAGE_LIMIT
        ).auto_paging_iter():
            for item in sub["items"]["data"]:
                summaries = stripe.SubscriptionItem.list_usage_record_summaries(
                    item["id"], api_key=key, limit=_PAGE_LIMIT
                )
                for summary in summaries.auto_paging_iter():
                    period = summary.get("period") or {}
                    raw = {
                        "id": summary["id"],
                        "customer_id": sub["customer"],
                        "metric": self._item_metric(item),
                        "quantity": summary.get("total_usage") or 0,
                        "occurred_at": period.get("start") or fallback_start,
                    }
                    yield usage_event_from_stripe(self._tenant_id, raw)

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        if not self._webhook_secret:
            raise ConnectorAuthError("Webhook secret not configured; call authenticate() first.")
        try:
            stripe.Webhook.construct_event(
                payload, signature, self._webhook_secret, tolerance=WEBHOOK_TOLERANCE_SECONDS
            )
        except stripe.SignatureVerificationError:
            return False
        return True

    @staticmethod
    def _line_metric(line: Any) -> str:
        price = line.get("price") or {}
        return str(line.get("description") or price.get("nickname") or "unknown")

    @staticmethod
    def _item_metric(item: Any) -> str:
        price = item.get("price") or {}
        return str(price.get("nickname") or price.get("id") or "unknown")
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_stripe_connector_unit.py tests/unit/test_stripe_mapping.py -q`
Expected: PASS (7 tests). (If `stripe.SignatureVerificationError` is not found at this import path in the installed version, use `stripe.error.SignatureVerificationError` — adjust the single `except` line.)

- [ ] **Step 10: Type-check, lint, commit**

Run: `uv run mypy && uv run ruff check . && uv run black --check . && uv run lint-imports`
Expected: clean; import contracts kept (domain still forbids `stripe`).

```bash
git add backend/src/yieldfield/infrastructure/connectors/base/connector.py \
  backend/src/yieldfield/infrastructure/connectors/stripe_billing/mapping.py \
  backend/src/yieldfield/infrastructure/connectors/stripe_billing/connector.py \
  backend/tests/unit/test_stripe_mapping.py backend/tests/unit/test_stripe_connector_unit.py
git commit -m "feat(connectors): Stripe Billing connector + base ABC (§17)"
```

---

## Task 9: Integration tests — OLTP repositories (testcontainers)

Disposable Postgres via testcontainers; run Alembic to `head`; round-trip aggregates and prove cross-tenant isolation (§11). All tests marked `integration`; the suite skips when Docker is unavailable.

**Files:**
- Create: `backend/tests/integration/conftest.py`
- Create: `backend/tests/integration/test_oltp_repositories.py`

- [ ] **Step 1: Create `tests/integration/conftest.py`**

```python
"""Docker-gated fixtures for integration tests (skip cleanly when Docker is absent)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_INI = REPO_ROOT / "ops" / "migrations" / "alembic.ini"


@pytest.fixture(scope="session")
def _postgres_container() -> Iterator[Any]:
    try:
        from testcontainers.postgres import PostgresContainer

        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:  # noqa: BLE001 - any startup failure means "no Docker here"
        pytest.skip(f"Docker/testcontainers unavailable: {exc}")
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def migrated_engine(_postgres_container: Any) -> Iterator[Engine]:
    from alembic import command
    from alembic.config import Config

    from yieldfield.infrastructure.persistence.engine import create_db_engine

    url = _postgres_container.get_connection_url()
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    engine = create_db_engine(url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(migrated_engine: Engine) -> Iterator[Session]:
    with Session(migrated_engine) as s:
        yield s
        s.rollback()
```

- [ ] **Step 2: Write the failing integration tests (`test_oltp_repositories.py`)**

```python
"""OLTP repository round-trips + cross-tenant isolation (§11). Requires Docker."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from yieldfield.domain.billing.invoice import Invoice, InvoiceLineItem
from yieldfield.domain.billing.plan import Plan
from yieldfield.domain.billing.tenant import Tenant
from yieldfield.domain.findings.finding import Finding, FindingLineage
from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.severity import Severity
from yieldfield.domain.reconciliation.reconciliation import Reconciliation
from yieldfield.domain.shared.ids import (
    FindingId,
    InvoiceId,
    InvoiceLineItemId,
    PlanId,
    ReconciliationId,
    TenantId,
)
from yieldfield.domain.shared.money import Money
from yieldfield.domain.shared.time_window import TimeWindow
from yieldfield.infrastructure.persistence.repositories import (
    SqlAlchemyFindingRepository,
    SqlAlchemyInvoiceRepository,
    SqlAlchemyPlanRepository,
    SqlAlchemyReconciliationRepository,
    SqlAlchemyTenantRepository,
)

pytestmark = pytest.mark.integration

_WINDOW = TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))


def _tenant(tid: str) -> Tenant:
    return Tenant(id=TenantId(tid), name=f"Tenant {tid}")


def _plan(tid: str, pid: str) -> Plan:
    return Plan(
        id=PlanId(pid),
        tenant_id=TenantId(tid),
        name="API calls",
        metric="api_call",
        unit_price=Money.of("0.0000004", "USD"),
    )


def test_plan_round_trips(session: Session) -> None:
    repo = SqlAlchemyPlanRepository(session)
    SqlAlchemyTenantRepository(session).add(_tenant("t_1"))
    repo.add(TenantId("t_1"), _plan("t_1", "pl_1"))
    session.flush()
    assert repo.get(TenantId("t_1"), PlanId("pl_1")) == _plan("t_1", "pl_1")


def test_invoice_round_trips_with_line_items(session: Session) -> None:
    SqlAlchemyTenantRepository(session).add(_tenant("t_1"))
    repo = SqlAlchemyInvoiceRepository(session)
    invoice = Invoice(
        id=InvoiceId("in_1"),
        tenant_id=TenantId("t_1"),
        customer_id="cus_1",
        period=_WINDOW,
        currency="USD",
        line_items=(
            InvoiceLineItem(
                id=InvoiceLineItemId("il_1"),
                metric="api_call",
                quantity=Decimal("1000"),
                amount=Money.of("4.00", "USD"),
            ),
        ),
    )
    repo.add(TenantId("t_1"), invoice)
    session.flush()
    assert repo.get(TenantId("t_1"), InvoiceId("in_1")) == invoice


def test_reconciliation_persists_findings_and_reads_back(session: Session) -> None:
    SqlAlchemyTenantRepository(session).add(_tenant("t_1"))
    finding = Finding(
        id=FindingId("fd_1"),
        tenant_id=TenantId("t_1"),
        reconciliation_id=ReconciliationId("rc_1"),
        customer_id="cus_1",
        metric="api_call",
        leakage_type=LeakageType.UNBILLED_USAGE,
        severity=Severity.HIGH,
        amount=Money.of("123.45", "USD"),
        status=RecoveryStatus.NEW,
        lineage=FindingLineage(rule_version="reconciliation-v1"),
        explanation="unbilled usage detected.",
    )
    recon = Reconciliation(
        id=ReconciliationId("rc_1"),
        tenant_id=TenantId("t_1"),
        window=_WINDOW,
        currency="USD",
        findings=(finding,),
    )
    SqlAlchemyReconciliationRepository(session).add(TenantId("t_1"), recon)
    session.flush()

    assert SqlAlchemyReconciliationRepository(session).get(TenantId("t_1"), ReconciliationId("rc_1")) == recon
    findings = SqlAlchemyFindingRepository(session).list_for_reconciliation(
        TenantId("t_1"), ReconciliationId("rc_1")
    )
    assert findings == [finding]


def test_finding_status_update_persists(session: Session) -> None:
    SqlAlchemyTenantRepository(session).add(_tenant("t_1"))
    finding = Finding(
        id=FindingId("fd_2"),
        tenant_id=TenantId("t_1"),
        reconciliation_id=ReconciliationId("rc_2"),
        customer_id="cus_1",
        metric="api_call",
        leakage_type=LeakageType.UNBILLED_USAGE,
        severity=Severity.HIGH,
        amount=Money.of("10.00", "USD"),
        status=RecoveryStatus.NEW,
        lineage=FindingLineage(rule_version="reconciliation-v1"),
        explanation="x",
    )
    recon = Reconciliation(
        id=ReconciliationId("rc_2"),
        tenant_id=TenantId("t_1"),
        window=_WINDOW,
        currency="USD",
        findings=(finding,),
    )
    repo = SqlAlchemyFindingRepository(session)
    SqlAlchemyReconciliationRepository(session).add(TenantId("t_1"), recon)
    session.flush()

    repo.update(TenantId("t_1"), finding.review())
    session.flush()
    reloaded = repo.get(TenantId("t_1"), FindingId("fd_2"))
    assert reloaded is not None
    assert reloaded.status is RecoveryStatus.REVIEWED


def test_cross_tenant_reads_are_isolated(session: Session) -> None:
    tenants = SqlAlchemyTenantRepository(session)
    plans = SqlAlchemyPlanRepository(session)
    tenants.add(_tenant("t_A"))
    tenants.add(_tenant("t_B"))
    plans.add(TenantId("t_A"), _plan("t_A", "pl_A"))
    session.flush()

    assert plans.get(TenantId("t_B"), PlanId("pl_A")) is None  # B cannot read A's plan
    assert plans.list_for_tenant(TenantId("t_B")) == []
    assert plans.get(TenantId("t_A"), PlanId("pl_A")) is not None
```

- [ ] **Step 3: Run the integration tests (Docker required)**

Run: `uv run pytest tests/integration/test_oltp_repositories.py -m integration -v`
Expected: PASS (5 tests). If Docker is not running, all are SKIPPED with the "Docker/testcontainers unavailable" reason — start Docker Desktop and re-run.

- [ ] **Step 4: Type-check + commit**

Run: `uv run mypy`
Expected: clean.

```bash
git add backend/tests/integration/conftest.py backend/tests/integration/test_oltp_repositories.py
git commit -m "test(persistence): OLTP repo round-trips + cross-tenant isolation (§11)"
```

---

## Task 10: Integration tests — ClickHouse usage-event store (testcontainers)

Disposable ClickHouse; `ensure_schema()`; append/query with half-open window boundary, `Decimal128(12)` precision, and tenant isolation (§11).

**Files:**
- Modify: `backend/tests/integration/conftest.py` (add `clickhouse_store` fixture)
- Create: `backend/tests/integration/test_clickhouse_store.py`

- [ ] **Step 1: Add the `clickhouse_store` fixture to `conftest.py`**

```python
@pytest.fixture(scope="session")
def clickhouse_store() -> Iterator[Any]:
    try:
        from testcontainers.clickhouse import ClickHouseContainer

        container = ClickHouseContainer("clickhouse/clickhouse-server:24.3-alpine")
        container.start()
    except Exception as exc:  # noqa: BLE001 - any startup failure means "no Docker here"
        pytest.skip(f"Docker/testcontainers unavailable: {exc}")
    try:
        import clickhouse_connect

        from yieldfield.infrastructure.analytics_store.clickhouse_usage_event_store import (
            ClickHouseUsageEventStore,
        )

        client = clickhouse_connect.get_client(
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(8123)),
            username=container.username,
            password=container.password,
            database=container.dbname,
        )
        store = ClickHouseUsageEventStore(client)
        store.ensure_schema()
        yield store
    finally:
        container.stop()
```

> If the installed `ClickHouseContainer` exposes different attribute names than
> `username`/`password`/`dbname`, the testcontainers defaults are user `test`, password
> `test`, db `test` — substitute literals if attribute access fails at runtime.

- [ ] **Step 2: Write the failing tests (`test_clickhouse_store.py`)**

```python
"""ClickHouse usage-event store: round-trip, window boundary, tenant isolation (§11)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.ids import TenantId, UsageEventId
from yieldfield.domain.shared.time_window import TimeWindow

pytestmark = pytest.mark.integration

_WINDOW = TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))


def _event(tid: str, eid: str, when: datetime, qty: str) -> UsageEvent:
    return UsageEvent(
        id=UsageEventId(eid),
        tenant_id=TenantId(tid),
        customer_id="cus_1",
        metric="api_call",
        quantity=Decimal(qty),
        occurred_at=when,
    )


def test_append_then_query_round_trips_with_decimal_precision(clickhouse_store: Any) -> None:
    event = _event("t_1", "ue_1", datetime(2026, 1, 15, tzinfo=UTC), "12.000000000123")
    clickhouse_store.append(TenantId("t_1"), [event])
    results = list(clickhouse_store.query(TenantId("t_1"), _WINDOW))
    assert event in results
    matched = next(e for e in results if e.id == "ue_1")
    assert matched.quantity == Decimal("12.000000000123")  # 12 fractional digits preserved


def test_query_excludes_events_on_the_window_end_boundary(clickhouse_store: Any) -> None:
    on_end = _event("t_1", "ue_end", datetime(2026, 2, 1, tzinfo=UTC), "1")  # == window.end → excluded
    clickhouse_store.append(TenantId("t_1"), [on_end])
    ids = {e.id for e in clickhouse_store.query(TenantId("t_1"), _WINDOW)}
    assert "ue_end" not in ids  # half-open [start, end)


def test_query_is_tenant_isolated(clickhouse_store: Any) -> None:
    clickhouse_store.append(TenantId("t_X"), [_event("t_X", "ue_x", datetime(2026, 1, 10, tzinfo=UTC), "5")])
    ids = {e.id for e in clickhouse_store.query(TenantId("t_Y"), _WINDOW)}
    assert "ue_x" not in ids  # tenant Y never sees tenant X's events (§11)
```

- [ ] **Step 3: Run the integration tests (Docker required)**

Run: `uv run pytest tests/integration/test_clickhouse_store.py -m integration -v`
Expected: PASS (3 tests), or SKIPPED without Docker.

> Note: these tests share one session-scoped ClickHouse table; each uses distinct event
> IDs/tenants so ordering is irrelevant. If flakiness appears, give each test a fresh
> store via a unique `table=` name.

- [ ] **Step 4: Type-check + commit**

Run: `uv run mypy`
Expected: clean.

```bash
git add backend/tests/integration/conftest.py backend/tests/integration/test_clickhouse_store.py
git commit -m "test(analytics): ClickHouse store round-trip, window boundary, tenant isolation (§11)"
```

---

## Task 11: Integration tests — Stripe connector (stripe-mock + gated live)

Deterministic CI coverage via `stripe/stripe-mock`; a live test-mode test that auto-skips without `STRIPE_TEST_SECRET_KEY` (no secrets committed, §11/§16).

**Files:**
- Modify: `backend/tests/integration/conftest.py` (add `stripe_mock_base_url` fixture)
- Create: `backend/tests/integration/test_stripe_connector_integration.py`

- [ ] **Step 1: Add the `stripe_mock_base_url` fixture to `conftest.py`**

```python
@pytest.fixture(scope="session")
def stripe_mock_base_url() -> Iterator[str]:
    try:
        from testcontainers.core.container import DockerContainer
        from testcontainers.core.waiting_utils import wait_for_logs

        container = DockerContainer("stripe/stripe-mock:latest").with_exposed_ports(12111)
        container.start()
        wait_for_logs(container, "Listening", timeout=30)
    except Exception as exc:  # noqa: BLE001 - any startup failure means "no Docker here"
        pytest.skip(f"Docker/testcontainers unavailable: {exc}")
    try:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(12111)
        yield f"http://{host}:{port}"
    finally:
        container.stop()
```

- [ ] **Step 2: Write the failing tests (`test_stripe_connector_integration.py`)**

```python
"""Stripe connector against stripe-mock (deterministic) + gated live test-mode."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
import stripe

from yieldfield.domain.billing.connector_port import ConnectorCredentials
from yieldfield.domain.billing.invoice import Invoice
from yieldfield.domain.shared.ids import TenantId
from yieldfield.domain.shared.time_window import TimeWindow
from yieldfield.infrastructure.connectors.stripe_billing.connector import StripeBillingConnector

pytestmark = pytest.mark.integration

_WIDE = TimeWindow(datetime(2015, 1, 1, tzinfo=UTC), datetime(2035, 1, 1, tzinfo=UTC))


@pytest.fixture
def _stripe_base(stripe_mock_base_url: str) -> Iterator[str]:
    original = stripe.api_base
    stripe.api_base = stripe_mock_base_url
    try:
        yield stripe_mock_base_url
    finally:
        stripe.api_base = original


def _connector() -> StripeBillingConnector:
    c = StripeBillingConnector(TenantId("t_1"))
    c.authenticate(ConnectorCredentials(secrets={"api_key": "sk_test_123", "webhook_secret": "whsec_x"}))
    return c


def test_pull_invoices_maps_mock_data_and_stamps_tenant(_stripe_base: str) -> None:
    invoices = list(_connector().pull_invoices(_WIDE))
    assert all(isinstance(i, Invoice) for i in invoices)
    assert all(i.tenant_id == "t_1" for i in invoices)  # tenant stamping (mock returns canned data)


def test_pull_usage_events_executes_against_mock(_stripe_base: str) -> None:
    events = list(_connector().pull_usage_events(_WIDE))  # may be empty; must not error
    assert all(e.tenant_id == "t_1" for e in events)


def test_live_test_mode_invoices_when_key_present() -> None:
    key = os.environ.get("STRIPE_TEST_SECRET_KEY")
    if not key:
        pytest.skip("STRIPE_TEST_SECRET_KEY not set; skipping live Stripe test-mode test")
    c = StripeBillingConnector(TenantId("t_1"))
    c.authenticate(ConnectorCredentials(secrets={"api_key": key}))
    invoices = list(c.pull_invoices(_WIDE))
    assert all(i.tenant_id == "t_1" for i in invoices)
```

- [ ] **Step 3: Run the integration tests (Docker required)**

Run: `uv run pytest tests/integration/test_stripe_connector_integration.py -m integration -v`
Expected: 2 PASS (stripe-mock), 1 SKIPPED (no `STRIPE_TEST_SECRET_KEY`); or all SKIPPED without Docker.

- [ ] **Step 4: Type-check + commit**

Run: `uv run mypy`
Expected: clean.

```bash
git add backend/tests/integration/conftest.py backend/tests/integration/test_stripe_connector_integration.py
git commit -m "test(connectors): Stripe connector vs stripe-mock + gated live test-mode (§11/§16)"
```

---

## Task 12: ClickHouse bootstrap script + CI wiring

Split CI so unit tests stay Docker-free (`-m "not integration"`) and a dedicated job runs the Docker-backed integration tests + Alembic. Add an ops script to provision the ClickHouse schema (not Alembic-managed).

**Files:**
- Create: `ops/scripts/bootstrap_clickhouse.py`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Create `ops/scripts/bootstrap_clickhouse.py`**

```python
"""Provision the ClickHouse OLAP schema (§12). ClickHouse is not Alembic-managed.

Run (from backend/, package installed):
    uv run python ../ops/scripts/bootstrap_clickhouse.py
Reads YIELDFIELD_CLICKHOUSE_URL from the environment (§16).
"""

from __future__ import annotations

import os
import sys

from yieldfield.infrastructure.analytics_store.clickhouse_client import create_clickhouse_client
from yieldfield.infrastructure.analytics_store.clickhouse_usage_event_store import (
    ClickHouseUsageEventStore,
)


def main() -> int:
    url = os.environ.get("YIELDFIELD_CLICKHOUSE_URL")
    client = create_clickhouse_client(url)
    ClickHouseUsageEventStore(client).ensure_schema()
    print("ClickHouse usage_events schema ensured.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Update the backend unit step in `.github/workflows/ci.yml` to exclude integration**

Change the existing step:

```yaml
      - name: Unit tests (money paths hardest, §7)
        run: uv run pytest
```

to:

```yaml
      - name: Unit tests (money paths hardest, §7)
        run: uv run pytest -m "not integration"
```

- [ ] **Step 3: Add an integration job to `.github/workflows/ci.yml`**

Add after the `backend:` job (sibling job; GitHub ubuntu runners provide Docker for testcontainers + stripe-mock):

```yaml
  integration:
    name: backend integration (Postgres · ClickHouse · stripe-mock)
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4

      - name: Install uv (also provisions Python 3.12)
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Install dependencies
        run: uv sync --frozen

      - name: Integration tests (testcontainers: Postgres/ClickHouse/stripe-mock, §11/§12/§15)
        run: uv run pytest -m integration -v
```

- [ ] **Step 4: Verify the unit suite is green and integration is selectable**

Run: `uv run pytest -m "not integration" -q`
Expected: PASS (all unit tests, no Docker needed).

Run: `uv run pytest -m integration -q`
Expected: PASS with Docker running (or SKIPPED without).

- [ ] **Step 5: Commit**

```bash
git add ops/scripts/bootstrap_clickhouse.py .github/workflows/ci.yml
git commit -m "ci(slice-2): split unit/integration jobs; add ClickHouse bootstrap script (§12/§15)"
```

---

## Task 13: Full verification sweep + slice report

**Files:** none (verification + report only).

- [ ] **Step 1: Run every backend gate**

Run (from `backend/`):
```bash
uv run ruff check .
uv run black --check .
uv run mypy
uv run lint-imports
uv run pytest -m "not integration" -q
uv run pytest -m integration -q
```
Expected: ruff clean; black clean; mypy `Success`; import-linter `Contracts: N kept, 0 broken` (domain still forbids `stripe`/`sqlalchemy`/`clickhouse_connect`); unit tests all pass; integration tests pass (Docker running) or skip (no Docker).

- [ ] **Step 2: Confirm domain purity held (spot-check)**

Run: `uv run lint-imports`
Expected: the "Domain is framework-pure" and "Domain imports no outer layer" contracts are kept — no persistence/connector import leaked into `domain/`.

- [ ] **Step 3: Sanity-check Alembic applies on a throwaway DB (if Docker available)**

Run: `uv run pytest tests/integration/test_oltp_repositories.py -m integration -q`
Expected: PASS — proves `alembic upgrade head` builds a schema the repositories round-trip against.

- [ ] **Step 4: Stop and report (per IMPLEMENTATION_PROMPT)**

Write the slice report to the user covering: what was built (OLTP repos, ClickHouse store, Stripe connector, migrations, tests), which sections it satisfies (§11, §12, §13, §16, §17), assumptions made (sync stack, two-decimal Stripe currency mapping, usage via subscription-item summaries, RLS deferred, ModelRunRepository deferred to Slice 5), test results (unit count + integration pass/skip), and the proposed next slice (Slice 3 — application use-cases + API + ingestion/reconciliation jobs). **Wait for go-ahead before Slice 3.**

- [ ] **Step 5: Final branch state check**

Run (from repo root): `git log --oneline main..slice-2-persistence-connector`
Expected: the design-spec commit plus one commit per task above, all on `slice-2-persistence-connector`.

---

## Self-Review (completed by plan author)

**Spec coverage:** every spec section maps to a task — ports §4→T1; OLTP adapter §5 + NUMERIC rationale §5.1→T2–T5; source-of-truth §3→T3/T5/T7 (TEXT[] lineage, ClickHouse usage events); OLAP §6→T7/T10; migrations §7→T6; tenant scoping §8→T5/T7/T9/T10 (guards + isolation tests); Stripe connector §9→T8/T11; testing §10→T9–T11; deps/guards §11→T0; workflow §12→branching already done + per-task commits; DoD §13→T13. RLS and ModelRunRepository are explicitly deferred (spec scope-out) — no task, by design.

**Placeholder scan:** no TBD/TODO; every code step contains complete code; commands have expected output.

**Type consistency:** port method names (`add`/`get`/`list_for_tenant`/`list_in_window`/`list_for_customer`/`list_for_reconciliation`/`update`/`append`/`query`) are used identically in the implementations and tests. Mapper names (`tenant_row`/`to_tenant`/`plan_row`/`to_plan`/`contract_row`/`to_contract`/`invoice_row`/`to_invoice`/`finding_row`/`to_finding`/`reconciliation_row`/`to_reconciliation`) match across `mappers.py`, `repositories.py`, and tests. `MONEY_SCALE`, `_storable`, `PersistenceError`, `AnalyticsStoreError`, `ConnectorAuthError`, `WEBHOOK_TOLERANCE_SECONDS`, `parse_clickhouse_url`, `create_clickhouse_client`, `ClickHouseUsageEventStore`, `StripeBillingConnector`, `invoice_from_stripe`, `usage_event_from_stripe` are defined once and referenced consistently.

**Known implementation-time adjustments (flagged inline, not placeholders):** the `stripe.SignatureVerificationError` import path and the `ClickHouseContainer` credential attribute names may vary by installed version — each has an explicit fallback noted at its step.

