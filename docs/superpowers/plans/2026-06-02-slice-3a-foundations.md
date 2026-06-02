# Slice 3A — Foundations & Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the persistence + infrastructure foundations Slice 3 needs — a credential cipher, a minimal persisted `Connector`, reconciliation audit columns, a persisted `Jobs` model, idempotent OLTP/OLAP writes, and a connector factory + registration service — so the application/API layers (Plans 3B/3C) can wire over them.

**Architecture:** Ports stay in `domain/`; adapters in `infrastructure/`. The `CredentialCipher` Protocol + Fernet impl live in a new `infrastructure/security/`. Connectors and Jobs are infrastructure-persisted concerns: the `Connector` *entity* is a pure domain concept, but its store contract (`ConnectorStore`) and the `Job` operational record live in infrastructure, so the application layer depends on domain ports only — enforced by a new 4th import-linter contract (`application ⊥ infrastructure`).

**Tech Stack:** Python 3.12, SQLAlchemy 2 (psycopg 3), Alembic, ClickHouse (`clickhouse-connect`), `cryptography` (Fernet), pytest + testcontainers, mypy strict, ruff, black, import-linter.

**Scope note:** This is **Plan 3A of 3** for Slice 3 (spec: `docs/superpowers/specs/2026-06-02-slice-3-application-api-jobs-design.md`, §15). It adds **no** application use-cases, API routes, webhooks, or workers — those are Plans 3B and 3C. In particular, the `run_as_job` orchestration wrapper and Celery tasks are **3C**; 3A delivers only the Jobs *table + value object + repository*.

**Branch:** continue on `slice-3-application-api-jobs` (HEAD at the Slice 2 tip `28d3be1`).

**Working directory:** all `uv` / `pytest` commands run from `backend/`. All file paths below are repo-relative.

---

## File structure (created/modified in 3A)

| File | Create/Modify | Responsibility |
|---|---|---|
| `backend/pyproject.toml` | Modify | Add `cryptography` dep; add 4th import-linter contract |
| `docs/ARCHITECTURE.md` | Modify | Document the new `infrastructure/security/` directory |
| `backend/src/yieldfield/config/settings.py` | Modify | `credentials_key`, `api_tokens`, `ingestion_enabled` |
| `.env.example` | Modify | Document the new env keys |
| `backend/src/yieldfield/infrastructure/security/__init__.py` | Create | Package marker |
| `backend/src/yieldfield/infrastructure/security/credential_cipher.py` | Create | `CredentialCipher` Protocol + `FernetCredentialCipher` |
| `backend/src/yieldfield/domain/shared/ids.py` | Modify | Add `ConnectorId` |
| `backend/src/yieldfield/domain/billing/connector.py` | Create | `Connector` entity + `ConnectorType`/`ConnectorStatus` |
| `backend/src/yieldfield/domain/reconciliation/reconciliation.py` | Modify | Add `executed_at`, `rule_version` |
| `backend/src/yieldfield/infrastructure/persistence/models.py` | Modify | `ConnectorRow`, `JobRow`; reconciliation audit columns |
| `backend/src/yieldfield/infrastructure/persistence/mappers.py` | Modify | Connector + reconciliation-audit mappers |
| `backend/src/yieldfield/infrastructure/persistence/job.py` | Create | `Job` value object + `JobType`/`JobStatus`/`JobResultType` enums |
| `backend/src/yieldfield/infrastructure/persistence/repositories.py` | Modify | `SqlAlchemyConnectorRepository`, `SqlAlchemyJobRepository`; idempotent invoice + reconciliation saves |
| `ops/migrations/versions/0002_connectors_jobs_recon_audit.py` | Create | Migration: connectors + jobs tables + reconciliation columns |
| `backend/src/yieldfield/infrastructure/analytics_store/clickhouse_usage_event_store.py` | Modify | `ReplacingMergeTree` + `FINAL` reads |
| `ops/scripts/bootstrap_clickhouse.py` | Modify | DDL → `ReplacingMergeTree` |
| `backend/src/yieldfield/infrastructure/connectors/factory.py` | Create | `build_connector(type → class)` |
| `backend/src/yieldfield/infrastructure/connectors/registration.py` | Create | `ConnectorStore` Protocol + `ConnectorRegistrationService` |
| `backend/tests/unit/test_*` | Create/Modify | Unit tests per task |
| `backend/tests/integration/test_*` | Create/Modify | Migration + repo + ClickHouse integration tests |

> **Ordering rule:** Tasks 5–7 add ORM columns/tables that don't exist in the DB until migration `0002` (Task 8). Their per-task gate runs **unit tests only** (`pytest tests/unit`). The Docker-backed integration suite is exercised from Task 8 onward, by which point `0002` is in place and the session-scoped `migrated_engine` fixture upgrades to head.

---

## Task 1: Dependency, import guard, and architecture doc

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Add the `cryptography` dependency**

In `backend/pyproject.toml`, in the `[project].dependencies` list, add after the `"stripe>=15,<16",` line:

```toml
    # Fernet symmetric encryption for connector credentials at rest (§11). Behind the
    # CredentialCipher seam, so an envelope/KMS impl can replace it later (§17).
    "cryptography>=43",
```

- [ ] **Step 2: Add the 4th import-linter contract**

In `backend/pyproject.toml`, append after the existing `"Domain imports no outer layer..."` contract block (the last contract in the file):

```toml
[[tool.importlinter.contracts]]
name = "Application depends only on the domain (not infrastructure)"
type = "forbidden"
source_modules = ["yieldfield.application"]
forbidden_modules = ["yieldfield.infrastructure"]
```

- [ ] **Step 3: Document `infrastructure/security/` in ARCHITECTURE.md**

In `docs/ARCHITECTURE.md`, in the `backend/` tree, add the `security/` line between `scoring_engine/` and `messaging/`:

```
│       │   ├── scoring_engine/  # Concrete Bayesian/ML implementations of scoring ports
│       │   ├── security/        # Secrets-at-rest: credential cipher (envelope-ready) — §11
│       │   ├── messaging/       # Queue producers/consumers, job orchestration
```

And in the "Backend directory responsibilities" table, add this row between the `infrastructure/scoring_engine/` row and the `infrastructure/messaging/` row:

```
| `infrastructure/security/` | Secrets at rest | Encrypt/decrypt connector credentials behind a cipher port | `CredentialCipher` + Fernet impl | §11 — credentials encrypted at rest, envelope-ready |
```

- [ ] **Step 4: Sync the lockfile and verify all four contracts pass**

Run:
```bash
uv lock
uv sync --group dev
uv run lint-imports
```
Expected: `Contracts: 4 kept, 0 broken.` (the new contract passes trivially — `application/` holds only empty `__init__.py` files).

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock docs/ARCHITECTURE.md
git commit -m "chore(slice-3): add cryptography dep + application⊥infrastructure import guard (§11/§6.1)"
```

---

## Task 2: Config settings additions

**Files:**
- Modify: `backend/src/yieldfield/config/settings.py`
- Modify: `.env.example`
- Test: `backend/tests/unit/test_settings.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/unit/test_settings.py`:

```python
def test_slice3_defaults() -> None:
    from yieldfield.config.settings import Settings

    settings = Settings()
    assert settings.ingestion_enabled is False
    assert settings.api_tokens == {}
    assert settings.credentials_key is None


def test_slice3_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    from yieldfield.config.settings import Settings

    monkeypatch.setenv("YIELDFIELD_INGESTION_ENABLED", "true")
    monkeypatch.setenv("YIELDFIELD_API_TOKENS", '{"tok_abc": "tenant-1"}')
    monkeypatch.setenv("YIELDFIELD_CREDENTIALS_KEY", "test-key")
    settings = Settings()
    assert settings.ingestion_enabled is True
    assert settings.api_tokens == {"tok_abc": "tenant-1"}
    assert settings.credentials_key == "test-key"
```

If `import pytest` is not already at the top of the file, add it.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_settings.py -q`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'ingestion_enabled'`.

- [ ] **Step 3: Add the settings fields**

In `backend/src/yieldfield/config/settings.py`, after the `clickhouse_url` field (the line `clickhouse_url: str | None = None  # ...`), add:

```python

    # ── Connector credentials & auth (§11, §16) — required when used ──────────
    # Fernet key for the credential cipher; required only when a connector is
    # registered/used (built lazily; fails fast there if absent).
    credentials_key: str | None = None
    # Bearer-token → tenant_id map backing the request auth dependency (Plan 3C).
    # Parsed from a JSON object in YIELDFIELD_API_TOKENS.
    api_tokens: dict[str, str] = Field(default_factory=dict)
    # Feature flag gating live billing-platform pulls (DoD: risky work behind a flag).
    ingestion_enabled: bool = False
```

(`Field` is already imported at the top of the file.)

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_settings.py -q`
Expected: PASS.

- [ ] **Step 5: Document the keys in `.env.example`**

In `.env.example`, after the `YIELDFIELD_CORS_ALLOW_ORIGINS=...` line, add:

```bash

# ── Connectors, credentials & auth (§11, §16) ────────────────────────────────
# Fernet key for connector-credential encryption at rest. Generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
YIELDFIELD_CREDENTIALS_KEY=
# Bearer-token → tenant map for the API auth dependency (LOCAL-ONLY example value).
YIELDFIELD_API_TOKENS={"local-dev-token":"tenant-local"}
# Gate live billing-platform pulls behind a flag.
YIELDFIELD_INGESTION_ENABLED=false
```

- [ ] **Step 6: Commit**

```bash
git add backend/src/yieldfield/config/settings.py backend/tests/unit/test_settings.py .env.example
git commit -m "feat(config): credentials_key, api_tokens, ingestion_enabled settings (§16)"
```

---

## Task 3: Credential cipher (`infrastructure/security/`)

**Files:**
- Create: `backend/src/yieldfield/infrastructure/security/__init__.py`
- Create: `backend/src/yieldfield/infrastructure/security/credential_cipher.py`
- Test: `backend/tests/unit/test_credential_cipher.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_credential_cipher.py`:

```python
"""FernetCredentialCipher round-trips secrets and fails loudly on bad input (§11)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from yieldfield.infrastructure.security.credential_cipher import (
    CredentialCipherError,
    FernetCredentialCipher,
)


def test_encrypt_decrypt_round_trip() -> None:
    cipher = FernetCredentialCipher(Fernet.generate_key().decode())
    secrets = {"api_key": "sk_test_123", "webhook_secret": "whsec_abc"}
    blob = cipher.encrypt(secrets)
    assert isinstance(blob, bytes)
    assert b"sk_test_123" not in blob  # ciphertext, not plaintext
    assert cipher.decrypt(blob) == secrets


def test_decrypt_with_wrong_key_raises() -> None:
    blob = FernetCredentialCipher(Fernet.generate_key().decode()).encrypt({"api_key": "x"})
    other = FernetCredentialCipher(Fernet.generate_key().decode())
    with pytest.raises(CredentialCipherError):
        other.decrypt(blob)


def test_invalid_key_raises() -> None:
    with pytest.raises(CredentialCipherError):
        FernetCredentialCipher("not-a-valid-fernet-key")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_credential_cipher.py -q`
Expected: FAIL — `ModuleNotFoundError: yieldfield.infrastructure.security.credential_cipher`.

- [ ] **Step 3: Create the package marker and implementation**

Create `backend/src/yieldfield/infrastructure/security/__init__.py` (empty file).

Create `backend/src/yieldfield/infrastructure/security/credential_cipher.py`:

```python
"""Credential encryption at rest (§11). A cipher *port* with a Fernet default.

Connector secrets are encrypted before they touch the OLTP store and decrypted only at
connector construction. The Protocol is the boundary, so the implementation can become
envelope/KMS-backed later without touching domain or application code (§17). Errors never
include the plaintext secret.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from cryptography.fernet import Fernet, InvalidToken


class CredentialCipherError(Exception):
    """Encryption/decryption failed. Never includes the plaintext secret (§11)."""


@runtime_checkable
class CredentialCipher(Protocol):
    """Encrypt/decrypt an opaque secrets mapping."""

    def encrypt(self, secrets: Mapping[str, str]) -> bytes: ...
    def decrypt(self, blob: bytes) -> Mapping[str, str]: ...


class FernetCredentialCipher:
    """Symmetric (Fernet/AES) cipher; key comes from config (§16) and is never logged."""

    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key)
        except (ValueError, TypeError) as exc:
            raise CredentialCipherError("Invalid Fernet key for the credential cipher.") from exc

    def encrypt(self, secrets: Mapping[str, str]) -> bytes:
        payload = json.dumps(dict(secrets), sort_keys=True).encode("utf-8")
        return self._fernet.encrypt(payload)

    def decrypt(self, blob: bytes) -> Mapping[str, str]:
        try:
            payload = self._fernet.decrypt(blob)
        except InvalidToken as exc:
            raise CredentialCipherError("Could not decrypt connector credentials.") from exc
        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, dict):
            raise CredentialCipherError("Decrypted credentials are not a mapping.")
        return {str(k): str(v) for k, v in data.items()}
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_credential_cipher.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/src/yieldfield/infrastructure/security/ backend/tests/unit/test_credential_cipher.py
git commit -m "feat(security): Fernet CredentialCipher behind a cipher port (§11/§17)"
```

---

## Task 4: Connector domain entity

> The connector **entity** is a business concept and lives in the domain. There is **no
> domain repository port** for connectors (spec §2.1): no inner layer depends on it, and the
> encrypted credential blob is not a business concept. The connector store contract is an
> infrastructure Protocol (Task 13), satisfied by `SqlAlchemyConnectorRepository` (Task 6).

**Files:**
- Modify: `backend/src/yieldfield/domain/shared/ids.py`
- Create: `backend/src/yieldfield/domain/billing/connector.py`
- Test: `backend/tests/unit/test_connector_entity.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_connector_entity.py`:

```python
"""Connector is a pure config entity carrying no secrets (§17, §11)."""

from __future__ import annotations

import pytest

from yieldfield.domain.billing.connector import Connector, ConnectorStatus, ConnectorType
from yieldfield.domain.shared.errors import InvalidEntityError
from yieldfield.domain.shared.ids import ConnectorId, TenantId


def test_connector_defaults_to_active() -> None:
    c = Connector(
        id=ConnectorId("con_1"),
        tenant_id=TenantId("tenant-1"),
        connector_type=ConnectorType.STRIPE_BILLING,
    )
    assert c.status is ConnectorStatus.ACTIVE
    assert c.connector_type.value == "stripe_billing"
    # No secret-bearing fields exist on the entity.
    assert not hasattr(c, "credentials")
    assert not hasattr(c, "encrypted_credentials")


def test_connector_requires_ids() -> None:
    with pytest.raises(InvalidEntityError):
        Connector(
            id=ConnectorId(""),
            tenant_id=TenantId("tenant-1"),
            connector_type=ConnectorType.STRIPE_BILLING,
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_connector_entity.py -q`
Expected: FAIL — `ModuleNotFoundError: yieldfield.domain.billing.connector`.

- [ ] **Step 3: Add `ConnectorId`**

In `backend/src/yieldfield/domain/shared/ids.py`, after the `ModelRunId = NewType("ModelRunId", str)` line, add:

```python
ConnectorId = NewType("ConnectorId", str)
```

- [ ] **Step 4: Create the entity**

Create `backend/src/yieldfield/domain/billing/connector.py`:

```python
"""Connector — a tenant's registered billing-platform integration config (§17, §11).

Pure: identity, type, and status only. The encrypted credential blob is a persistence
concern and never lives on this entity — the domain never sees secrets (§11). A new
platform = a new ConnectorType member + a concrete connector class behind the port (§17).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from yieldfield.domain.shared.errors import InvalidEntityError
from yieldfield.domain.shared.ids import ConnectorId, TenantId


class ConnectorType(StrEnum):
    STRIPE_BILLING = "stripe_billing"


class ConnectorStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class Connector:
    id: ConnectorId
    tenant_id: TenantId
    connector_type: ConnectorType
    status: ConnectorStatus = ConnectorStatus.ACTIVE

    def __post_init__(self) -> None:
        if not str(self.id).strip():
            raise InvalidEntityError("Connector id is required.")
        if not str(self.tenant_id).strip():
            raise InvalidEntityError("Connector tenant_id is required.")
```

- [ ] **Step 5: Run to verify it passes + domain stays pure**

Run:
```bash
uv run pytest tests/unit/test_connector_entity.py -q
uv run lint-imports
```
Expected: tests PASS; `Contracts: 4 kept, 0 broken.`

- [ ] **Step 6: Commit**

```bash
git add backend/src/yieldfield/domain/ backend/tests/unit/test_connector_entity.py
git commit -m "feat(domain): Connector config entity + type/status enums (§17)"
```

---

## Task 5: Reconciliation audit columns (domain + persistence + call sites)

> The domain entity, ORM columns, mappers, and every existing `Reconciliation(...)` call
> site change **together** so the commit stays green: the mapper constructs `Reconciliation`,
> so it must learn the new required fields in the same commit.

**Files:**
- Modify: `backend/src/yieldfield/domain/reconciliation/reconciliation.py`
- Modify: `backend/src/yieldfield/infrastructure/persistence/models.py`
- Modify: `backend/src/yieldfield/infrastructure/persistence/mappers.py`
- Modify (call sites): `backend/tests/unit/test_reconciliation.py`, `backend/tests/unit/test_persistence_mappers.py`, `backend/tests/integration/test_oltp_repositories.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/unit/test_reconciliation.py`:

```python
def test_reconciliation_carries_audit_fields() -> None:
    executed = datetime(2026, 6, 1, tzinfo=UTC)
    recon = Reconciliation(
        id=ReconciliationId("rec_1"),
        tenant_id=TenantId("t_1"),
        window=_window(),
        currency="USD",
        executed_at=executed,
        rule_version="reconciliation-v1",
    )
    assert recon.executed_at == executed
    assert recon.rule_version == "reconciliation-v1"
    assert recon.finding_count == 0
```

(The file already imports `UTC`, `datetime`, `Reconciliation`, `ReconciliationId`, `TenantId` and defines `_window()`.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_reconciliation.py::test_reconciliation_carries_audit_fields -q`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'executed_at'`.

- [ ] **Step 3: Add the domain fields**

In `backend/src/yieldfield/domain/reconciliation/reconciliation.py`, change the imports line `from dataclasses import dataclass` block to also import `datetime`:

```python
from dataclasses import dataclass
from datetime import datetime
```

Change the dataclass so `executed_at` and `rule_version` are required and precede the defaulted `findings`:

```python
@dataclass(frozen=True, slots=True)
class Reconciliation:
    id: ReconciliationId
    tenant_id: TenantId
    window: TimeWindow
    currency: str
    executed_at: datetime
    rule_version: str
    findings: tuple[Finding, ...] = ()
```

(Leave `total_leakage()` and `finding_count` unchanged.)

- [ ] **Step 4: Add the ORM columns**

In `backend/src/yieldfield/infrastructure/persistence/models.py`, add `func` to the SQLAlchemy import line:

```python
from sqlalchemy import ForeignKey, Numeric, String, Text, func
```

In `ReconciliationRow`, add after the `currency` column:

```python
    executed_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    rule_version: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="reconciliation-v1"
    )
```

- [ ] **Step 5: Update the reconciliation mappers**

In `backend/src/yieldfield/infrastructure/persistence/mappers.py`, replace `reconciliation_row` and `to_reconciliation` so they carry the audit fields:

```python
def reconciliation_row(recon: Reconciliation) -> ReconciliationRow:
    row = ReconciliationRow(
        id=recon.id,
        tenant_id=recon.tenant_id,
        window_start=recon.window.start,
        window_end=recon.window.end,
        currency=recon.currency,
        executed_at=recon.executed_at,
        rule_version=recon.rule_version,
    )
    row.findings = [finding_row(f, TenantId(recon.tenant_id)) for f in recon.findings]
    return row


def to_reconciliation(row: ReconciliationRow) -> Reconciliation:
    return Reconciliation(
        id=ReconciliationId(row.id),
        tenant_id=TenantId(row.tenant_id),
        window=TimeWindow(row.window_start, row.window_end),
        currency=row.currency,
        executed_at=row.executed_at,
        rule_version=row.rule_version,
        findings=tuple(to_finding(fr) for fr in row.findings),
    )
```

- [ ] **Step 6: Fix the existing call sites**

In `backend/tests/unit/test_persistence_mappers.py`, the `Reconciliation(...)` at the `test_reconciliation_round_trip_preserves_findings_and_lineage` test (around line 83) — add the two fields before `findings=`:

```python
    recon = Reconciliation(
        id=ReconciliationId("rc_1"),
        tenant_id=TenantId("t_1"),
        window=_WINDOW,
        currency="USD",
        executed_at=datetime(2026, 1, 1, tzinfo=UTC),
        rule_version="reconciliation-v1",
        findings=(finding,),
    )
```

If `from datetime import UTC, datetime` is not already imported at the top of that file, add it.

In `backend/tests/integration/test_oltp_repositories.py`, both `Reconciliation(...)` constructions (in `test_reconciliation_round_trip_preserves_findings_and_lineage` and `test_finding_status_update_persists`) — add the same two fields before `findings=`:

```python
        executed_at=datetime(2026, 1, 1, tzinfo=UTC),
        rule_version="reconciliation-v1",
```

If `from datetime import UTC, datetime` is not already imported at the top of that file, add it.

- [ ] **Step 7: Run the unit suite + mypy**

Run:
```bash
uv run pytest tests/unit -q
uv run mypy
```
Expected: unit tests PASS (incl. `test_reconciliation_carries_audit_fields`); mypy `Success`. (If mypy or pytest reports any other file constructing `Reconciliation(...)` without the new fields, add the two fields there too.)

- [ ] **Step 8: Commit**

```bash
git add backend/src/yieldfield/domain/reconciliation/reconciliation.py backend/src/yieldfield/infrastructure/persistence/models.py backend/src/yieldfield/infrastructure/persistence/mappers.py backend/tests/unit/test_reconciliation.py backend/tests/unit/test_persistence_mappers.py backend/tests/integration/test_oltp_repositories.py
git commit -m "feat(reconciliation): executed_at + rule_version on entity, ORM, and mappers (§7/§12)"
```

---

## Task 6: Connector persistence (model, mapper, repository)

**Files:**
- Modify: `backend/src/yieldfield/infrastructure/persistence/models.py`
- Modify: `backend/src/yieldfield/infrastructure/persistence/mappers.py`
- Modify: `backend/src/yieldfield/infrastructure/persistence/repositories.py`
- Test: `backend/tests/unit/test_persistence_mappers.py`, `backend/tests/unit/test_persistence_models.py`

- [ ] **Step 1: Write the failing mapper test**

Append to `backend/tests/unit/test_persistence_mappers.py`:

```python
def test_connector_row_round_trip() -> None:
    from yieldfield.domain.billing.connector import (
        Connector,
        ConnectorStatus,
        ConnectorType,
    )
    from yieldfield.domain.shared.ids import ConnectorId, TenantId
    from yieldfield.infrastructure.persistence import mappers

    connector = Connector(
        id=ConnectorId("con_1"),
        tenant_id=TenantId("tenant-1"),
        connector_type=ConnectorType.STRIPE_BILLING,
        status=ConnectorStatus.ACTIVE,
    )
    row = mappers.connector_row(connector, b"ENCRYPTED")
    assert row.id == "con_1"
    assert row.connector_type == "stripe_billing"
    assert row.encrypted_credentials == b"ENCRYPTED"
    assert mappers.to_connector(row) == connector
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_persistence_mappers.py::test_connector_row_round_trip -q`
Expected: FAIL — `AttributeError: module 'yieldfield.infrastructure.persistence.mappers' has no attribute 'connector_row'`.

- [ ] **Step 3: Add the `ConnectorRow` model**

In `backend/src/yieldfield/infrastructure/persistence/models.py`, add `LargeBinary` to the SQLAlchemy import line (Task 5 already added `func`):

```python
from sqlalchemy import ForeignKey, LargeBinary, Numeric, String, Text, func
```

Add a `connectors` relationship to `TenantRow` (after the existing `findings` relationship line):

```python
    connectors: Mapped[list[ConnectorRow]] = relationship(back_populates="tenant")
```

Append a new model after `FindingRow`:

```python
class ConnectorRow(Base):
    __tablename__ = "connectors"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.id"), nullable=False, index=True
    )
    connector_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_credentials: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        _TS, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    tenant: Mapped[TenantRow] = relationship(back_populates="connectors")
```

- [ ] **Step 4: Add the connector mappers**

In `backend/src/yieldfield/infrastructure/persistence/mappers.py`, add these imports (merge `ConnectorId` into the existing `ids` import block and `ConnectorRow` into the existing `models` import block; add the new `connector` import line):

```python
from yieldfield.domain.billing.connector import Connector, ConnectorStatus, ConnectorType
```
```python
from yieldfield.domain.shared.ids import (
    ConnectorId,
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
```
```python
from yieldfield.infrastructure.persistence.models import (
    MONEY_SCALE,
    ConnectorRow,
    ContractRow,
    FindingRow,
    InvoiceLineItemRow,
    InvoiceRow,
    PlanRow,
    ReconciliationRow,
    TenantRow,
)
```

Append the connector mappers at the end of the file:

```python
# ── Connector ────────────────────────────────────────────────────────────────
def connector_row(connector: Connector, encrypted_credentials: bytes) -> ConnectorRow:
    return ConnectorRow(
        id=connector.id,
        tenant_id=connector.tenant_id,
        connector_type=connector.connector_type.value,
        status=connector.status.value,
        encrypted_credentials=encrypted_credentials,
    )


def to_connector(row: ConnectorRow) -> Connector:
    return Connector(
        id=ConnectorId(row.id),
        tenant_id=TenantId(row.tenant_id),
        connector_type=ConnectorType(row.connector_type),
        status=ConnectorStatus(row.status),
    )
```

- [ ] **Step 5: Add the `SqlAlchemyConnectorRepository`**

In `backend/src/yieldfield/infrastructure/persistence/repositories.py`, add imports (merge `ConnectorId` into the `ids` block and `ConnectorRow` into the `models` block; add the `connector` import):

```python
from yieldfield.domain.billing.connector import Connector
```
```python
from yieldfield.domain.shared.ids import (
    ConnectorId,
    ContractId,
    FindingId,
    InvoiceId,
    PlanId,
    ReconciliationId,
    TenantId,
)
```
```python
from yieldfield.infrastructure.persistence.models import (
    ConnectorRow,
    ContractRow,
    FindingRow,
    InvoiceRow,
    PlanRow,
    ReconciliationRow,
    TenantRow,
)
```

Append the repository at the end of the file:

```python
class SqlAlchemyConnectorRepository:
    """Connector config + encrypted-credential persistence (the infra ConnectorStore, §2.1)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(
        self, tenant_id: TenantId, connector: Connector, encrypted_credentials: bytes
    ) -> None:
        _guard(tenant_id, connector.tenant_id)
        self._session.add(mappers.connector_row(connector, encrypted_credentials))

    def get(self, tenant_id: TenantId, connector_id: ConnectorId) -> Connector | None:
        row = self._session.scalars(
            select(ConnectorRow).where(
                ConnectorRow.id == str(connector_id),
                ConnectorRow.tenant_id == str(tenant_id),
            )
        ).first()
        return mappers.to_connector(row) if row is not None else None

    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Connector]:
        rows = self._session.scalars(
            select(ConnectorRow)
            .where(ConnectorRow.tenant_id == str(tenant_id))
            .order_by(ConnectorRow.id)
        ).all()
        return [mappers.to_connector(r) for r in rows]

    def load_credentials(
        self, tenant_id: TenantId, connector_id: ConnectorId
    ) -> bytes | None:
        row = self._session.scalars(
            select(ConnectorRow).where(
                ConnectorRow.id == str(connector_id),
                ConnectorRow.tenant_id == str(tenant_id),
            )
        ).first()
        return row.encrypted_credentials if row is not None else None

    def find_by_id(self, connector_id: ConnectorId) -> Connector | None:
        """Resolve a connector (incl. its tenant) by id alone — the webhook-ingress
        resolver (§6). This is the single deliberate non-tenant-prescoped read; the id is
        the routing key and the webhook signature gates processing (§11)."""
        row = self._session.get(ConnectorRow, str(connector_id))
        return mappers.to_connector(row) if row is not None else None
```

- [ ] **Step 6: Update the ORM schema-shape unit tests**

In `backend/tests/unit/test_persistence_models.py`, add `"connectors"` to the expected set in `test_all_oltp_tables_present`:

```python
def test_all_oltp_tables_present() -> None:
    assert set(metadata.tables) == {
        "tenants",
        "plans",
        "contracts",
        "invoices",
        "invoice_line_items",
        "reconciliations",
        "findings",
        "connectors",
    }
```

And add `"connectors"` to the tuple in `test_every_tenant_owned_table_has_an_indexed_tenant_id`:

```python
    for name in (
        "plans",
        "contracts",
        "invoices",
        "invoice_line_items",
        "reconciliations",
        "findings",
        "connectors",
    ):
```

- [ ] **Step 7: Run mapper + model tests + type check**

Run:
```bash
uv run pytest tests/unit/test_persistence_mappers.py tests/unit/test_persistence_models.py -q
uv run mypy
```
Expected: tests PASS; mypy `Success`.

- [ ] **Step 8: Commit**

```bash
git add backend/src/yieldfield/infrastructure/persistence/ backend/tests/unit/test_persistence_mappers.py backend/tests/unit/test_persistence_models.py
git commit -m "feat(persistence): connectors table + repository + mappers (§11)"
```

---

## Task 7: Jobs persistence (value object, model, repository)

> The `Job` is an **operational** record (execution lifecycle), kept out of the pure domain
> and out of the application use-cases (spec §3). The `run_as_job` wrapper and Celery tasks
> are Plan 3C; here we build the table + value object + repository only.

**Files:**
- Create: `backend/src/yieldfield/infrastructure/persistence/job.py`
- Modify: `backend/src/yieldfield/infrastructure/persistence/models.py`
- Modify: `backend/src/yieldfield/infrastructure/persistence/repositories.py`
- Test: `backend/tests/unit/test_job.py`, `backend/tests/unit/test_persistence_models.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_job.py`:

```python
"""Job is a lightweight operational record; its result reference is null-or-both-set (§3, G)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from yieldfield.domain.shared.ids import TenantId
from yieldfield.infrastructure.persistence.errors import PersistenceError
from yieldfield.infrastructure.persistence.job import (
    Job,
    JobResultType,
    JobStatus,
    JobType,
)

_CREATED = datetime(2026, 6, 1, tzinfo=UTC)


def test_pending_job_has_no_result() -> None:
    job = Job(
        id="job_1",
        tenant_id=TenantId("tenant-1"),
        job_type=JobType.RUN_RECONCILIATION,
        status=JobStatus.PENDING,
        created_at=_CREATED,
    )
    assert job.status is JobStatus.PENDING
    assert job.result_type is None
    assert job.result_ref is None


def test_result_type_without_ref_raises() -> None:
    with pytest.raises(PersistenceError):
        Job(
            id="job_1",
            tenant_id=TenantId("tenant-1"),
            job_type=JobType.RUN_RECONCILIATION,
            status=JobStatus.SUCCEEDED,
            created_at=_CREATED,
            result_type=JobResultType.RECONCILIATION,
        )


def test_result_ref_without_type_raises() -> None:
    with pytest.raises(PersistenceError):
        Job(
            id="job_1",
            tenant_id=TenantId("tenant-1"),
            job_type=JobType.RUN_RECONCILIATION,
            status=JobStatus.SUCCEEDED,
            created_at=_CREATED,
            result_ref="rec_1",
        )


def test_succeeded_job_with_result_pair_is_valid() -> None:
    job = Job(
        id="job_1",
        tenant_id=TenantId("tenant-1"),
        job_type=JobType.RUN_RECONCILIATION,
        status=JobStatus.SUCCEEDED,
        created_at=_CREATED,
        result_type=JobResultType.RECONCILIATION,
        result_ref="rec_1",
    )
    assert job.result_type is JobResultType.RECONCILIATION
    assert job.result_ref == "rec_1"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_job.py -q`
Expected: FAIL — `ModuleNotFoundError: yieldfield.infrastructure.persistence.job`.

- [ ] **Step 3: Create the `Job` value object + enums**

Create `backend/src/yieldfield/infrastructure/persistence/job.py`:

```python
"""The Job operational record (§3) — execution lifecycle, distinct from the financial
Reconciliation record. Infrastructure-only: the pure domain and the application use-cases
never see it. The result reference is a generic (result_type, result_ref) pair so future
job types reference different artifacts with no schema change (spec decision G).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from yieldfield.domain.shared.ids import TenantId
from yieldfield.infrastructure.persistence.errors import PersistenceError


class JobType(StrEnum):
    RUN_RECONCILIATION = "run_reconciliation"
    INGEST_INVOICES = "ingest_invoices"
    INGEST_USAGE_EVENTS = "ingest_usage_events"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobResultType(StrEnum):
    RECONCILIATION = "reconciliation"


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    tenant_id: TenantId
    job_type: JobType
    status: JobStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    result_type: JobResultType | None = None
    result_ref: str | None = None
    celery_task_id: str | None = None

    def __post_init__(self) -> None:
        if (self.result_type is None) != (self.result_ref is None):
            raise PersistenceError(
                "Job result_type and result_ref must be set together (spec decision G)."
            )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_job.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Add the `JobRow` model**

In `backend/src/yieldfield/infrastructure/persistence/models.py`, add `CheckConstraint` to the SQLAlchemy import line:

```python
from sqlalchemy import CheckConstraint, ForeignKey, LargeBinary, Numeric, String, Text, func
```

Add a `jobs` relationship to `TenantRow` (after the `connectors` relationship line added in Task 6):

```python
    jobs: Mapped[list[JobRow]] = relationship(back_populates="tenant")
```

Append a new model after `ConnectorRow`:

```python
class JobRow(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "(result_type IS NULL) = (result_ref IS NULL)", name="ck_jobs_result_pair"
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.id"), nullable=False, index=True
    )
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(_TS, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    tenant: Mapped[TenantRow] = relationship(back_populates="jobs")
```

- [ ] **Step 6: Add the `SqlAlchemyJobRepository`**

In `backend/src/yieldfield/infrastructure/persistence/repositories.py`, add imports (merge `JobRow` into the `models` block; add the `job` import):

```python
from yieldfield.infrastructure.persistence.job import Job, JobResultType, JobStatus, JobType
```
```python
from yieldfield.infrastructure.persistence.models import (
    ConnectorRow,
    ContractRow,
    FindingRow,
    InvoiceRow,
    JobRow,
    PlanRow,
    ReconciliationRow,
    TenantRow,
)
```

Append the row↔Job helpers and the repository at the end of the file:

```python
def _job_row(job: Job) -> JobRow:
    return JobRow(
        id=job.id,
        tenant_id=job.tenant_id,
        job_type=job.job_type.value,
        status=job.status.value,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error=job.error,
        result_type=job.result_type.value if job.result_type is not None else None,
        result_ref=job.result_ref,
        celery_task_id=job.celery_task_id,
    )


def _to_job(row: JobRow) -> Job:
    return Job(
        id=row.id,
        tenant_id=TenantId(row.tenant_id),
        job_type=JobType(row.job_type),
        status=JobStatus(row.status),
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        error=row.error,
        result_type=JobResultType(row.result_type) if row.result_type is not None else None,
        result_ref=row.result_ref,
        celery_task_id=row.celery_task_id,
    )


class SqlAlchemyJobRepository:
    """Durable operational job ledger (§3). Authoritative status surface for GET /jobs (3C)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, tenant_id: TenantId, job: Job) -> None:
        _guard(tenant_id, job.tenant_id)
        self._session.add(_job_row(job))

    def get(self, tenant_id: TenantId, job_id: str) -> Job | None:
        row = self._session.scalars(
            select(JobRow).where(JobRow.id == job_id, JobRow.tenant_id == str(tenant_id))
        ).first()
        return _to_job(row) if row is not None else None

    def update(self, tenant_id: TenantId, job: Job) -> None:
        _guard(tenant_id, job.tenant_id)
        row = self._session.get(JobRow, job.id)
        if row is None or str(row.tenant_id) != str(tenant_id):
            raise PersistenceError(f"Job {job.id!r} not found for tenant {tenant_id!r}.")
        row.status = job.status.value
        row.started_at = job.started_at
        row.finished_at = job.finished_at
        row.error = job.error
        row.result_type = job.result_type.value if job.result_type is not None else None
        row.result_ref = job.result_ref
        row.celery_task_id = job.celery_task_id
```

- [ ] **Step 7: Update the ORM schema-shape unit tests**

In `backend/tests/unit/test_persistence_models.py`, add `"jobs"` to the expected set in `test_all_oltp_tables_present`:

```python
        "connectors",
        "jobs",
    }
```

And add `"jobs"` to the tuple in `test_every_tenant_owned_table_has_an_indexed_tenant_id`:

```python
        "connectors",
        "jobs",
    ):
```

- [ ] **Step 8: Run unit tests + type check**

Run:
```bash
uv run pytest tests/unit -q
uv run mypy
```
Expected: tests PASS; mypy `Success`.

- [ ] **Step 9: Commit**

```bash
git add backend/src/yieldfield/infrastructure/persistence/ backend/tests/unit/test_job.py backend/tests/unit/test_persistence_models.py
git commit -m "feat(persistence): jobs table + Job value object + repository (§3/§13)"
```

---

## Task 8: Alembic migration `0002` (connectors + jobs + reconciliation audit)

**Files:**
- Create: `ops/migrations/versions/0002_connectors_jobs_recon_audit.py`
- Test: `backend/tests/integration/test_migrations.py`

- [ ] **Step 1: Write the failing migration round-trip test**

Create `backend/tests/integration/test_migrations.py`:

```python
"""Migration 0002 applies and reverses on a disposable Postgres (§12).

Uses its OWN throwaway container so it never downgrades the session-scoped
`migrated_engine` database that the other integration tests share.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

REPO_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_INI = REPO_ROOT / "ops" / "migrations" / "alembic.ini"


@pytest.fixture
def fresh_pg_url() -> Iterator[str]:
    try:
        from testcontainers.postgres import PostgresContainer

        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:  # any startup failure means Docker isn't available here
        pytest.skip(f"Docker/testcontainers unavailable: {exc}")
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


@pytest.mark.integration
def test_migration_0002_upgrades_and_downgrades(fresh_pg_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", fresh_pg_url)

    command.upgrade(cfg, "head")
    engine = create_engine(fresh_pg_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"connectors", "jobs"} <= tables
    recon_cols = {c["name"] for c in inspector.get_columns("reconciliations")}
    assert {"executed_at", "rule_version"} <= recon_cols
    engine.dispose()

    command.downgrade(cfg, "0001_oltp_schema")
    engine = create_engine(fresh_pg_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "connectors" not in tables
    assert "jobs" not in tables
    recon_cols = {c["name"] for c in inspector.get_columns("reconciliations")}
    assert "executed_at" not in recon_cols
    engine.dispose()
```

- [ ] **Step 2: Run to verify it fails (or skips without Docker)**

Run: `uv run pytest tests/integration/test_migrations.py -q -m integration`
Expected: with Docker — FAIL (`connectors`/`jobs` not created; upgrade has nothing new past 0001). Without Docker — SKIP. **Start Docker Desktop** so this runs.

- [ ] **Step 3: Write the migration**

Create `ops/migrations/versions/0002_connectors_jobs_recon_audit.py`:

```python
"""Connectors + jobs tables and reconciliation audit columns (executed_at, rule_version).

Forward-only (§12) with a working downgrade. Connector credentials are stored as an opaque
encrypted BYTEA (§11); jobs are an operational ledger (§3) whose (result_type, result_ref)
pair is null-or-both-set.

Revision ID: 0002_connectors_jobs_recon_audit
Revises: 0001_oltp_schema
Create Date: 2026-06-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_connectors_jobs_recon_audit"
down_revision = "0001_oltp_schema"
branch_labels = None
depends_on = None

_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "connectors",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("connector_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("encrypted_credentials", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", _TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_connectors_tenant_id", "connectors", ["tenant_id"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", _TS, nullable=True),
        sa.Column("finished_at", _TS, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result_type", sa.Text(), nullable=True),
        sa.Column("result_ref", sa.Text(), nullable=True),
        sa.Column("celery_task_id", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "(result_type IS NULL) = (result_ref IS NULL)", name="ck_jobs_result_pair"
        ),
    )
    op.create_index("ix_jobs_tenant_id", "jobs", ["tenant_id"])

    op.add_column(
        "reconciliations",
        sa.Column("executed_at", _TS, nullable=False, server_default=sa.func.now()),
    )
    op.add_column(
        "reconciliations",
        sa.Column(
            "rule_version", sa.Text(), nullable=False, server_default="reconciliation-v1"
        ),
    )


def downgrade() -> None:
    op.drop_column("reconciliations", "rule_version")
    op.drop_column("reconciliations", "executed_at")
    op.drop_index("ix_jobs_tenant_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_connectors_tenant_id", table_name="connectors")
    op.drop_table("connectors")
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/integration/test_migrations.py -q -m integration`
Expected: PASS (with Docker running).

- [ ] **Step 5: Commit**

```bash
git add ops/migrations/versions/0002_connectors_jobs_recon_audit.py backend/tests/integration/test_migrations.py
git commit -m "feat(migrations): 0002 connectors + jobs tables + reconciliation audit columns (§12)"
```

---

## Task 9: Idempotent OLTP saves (invoice + reconciliation upsert)

**Files:**
- Modify: `backend/src/yieldfield/infrastructure/persistence/repositories.py`
- Test: `backend/tests/integration/test_oltp_repositories.py`

- [ ] **Step 1: Write the failing integration test**

Append to `backend/tests/integration/test_oltp_repositories.py` (it already has the `session` fixture and helpers; this test is self-contained with local imports):

```python
@pytest.mark.integration
def test_invoice_add_is_idempotent(session: Session) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    from yieldfield.domain.billing.invoice import Invoice, InvoiceLineItem
    from yieldfield.domain.billing.tenant import Tenant
    from yieldfield.domain.shared.ids import InvoiceId, InvoiceLineItemId, TenantId
    from yieldfield.domain.shared.money import Money
    from yieldfield.domain.shared.time_window import TimeWindow
    from yieldfield.infrastructure.persistence.repositories import (
        SqlAlchemyInvoiceRepository,
        SqlAlchemyTenantRepository,
    )

    tid = TenantId("tenant-idem")
    SqlAlchemyTenantRepository(session).add(Tenant(id=tid, name="Idem"))
    session.flush()
    repo = SqlAlchemyInvoiceRepository(session)
    period = TimeWindow(datetime(2026, 5, 1, tzinfo=UTC), datetime(2026, 6, 1, tzinfo=UTC))

    def build(amount: str) -> Invoice:
        return Invoice(
            id=InvoiceId("inv_1"),
            tenant_id=tid,
            customer_id="cus_1",
            period=period,
            currency="USD",
            line_items=(
                InvoiceLineItem(
                    id=InvoiceLineItemId("li_1"),
                    metric="api_calls",
                    quantity=Decimal("10"),
                    amount=Money.of(amount, "USD"),
                ),
            ),
        )

    repo.add(tid, build("100"))
    session.flush()
    repo.add(tid, build("250"))  # same id again — must replace, not duplicate
    session.flush()

    stored = repo.get(tid, InvoiceId("inv_1"))
    assert stored is not None
    assert stored.total() == Money.of("250", "USD")
    assert len(stored.line_items) == 1  # line items replaced, not accumulated
```

- [ ] **Step 2: Run to verify it fails (or skips without Docker)**

Run: `uv run pytest tests/integration/test_oltp_repositories.py::test_invoice_add_is_idempotent -q -m integration`
Expected: with Docker — FAIL (duplicate primary key on the second `add`). Without Docker — SKIP.

- [ ] **Step 3: Make invoice + reconciliation saves idempotent**

In `backend/src/yieldfield/infrastructure/persistence/repositories.py`, change `SqlAlchemyInvoiceRepository.add` to upsert-by-id:

```python
    def add(self, tenant_id: TenantId, invoice: Invoice) -> None:
        _guard(tenant_id, invoice.tenant_id)
        existing = self._session.get(InvoiceRow, str(invoice.id))
        if existing is not None:
            _guard(tenant_id, existing.tenant_id)
            self._session.delete(existing)  # cascade removes its line items
            self._session.flush()
        self._session.add(mappers.invoice_row(invoice))
```

Apply the same pattern to `SqlAlchemyReconciliationRepository.add`:

```python
    def add(self, tenant_id: TenantId, reconciliation: Reconciliation) -> None:
        _guard(tenant_id, reconciliation.tenant_id)
        existing = self._session.get(ReconciliationRow, str(reconciliation.id))
        if existing is not None:
            _guard(tenant_id, existing.tenant_id)
            self._session.delete(existing)  # cascade removes its findings
            self._session.flush()
        self._session.add(mappers.reconciliation_row(reconciliation))
```

- [ ] **Step 4: Run to verify it passes (full file, to confirm no regression)**

Run: `uv run pytest tests/integration/test_oltp_repositories.py -q -m integration`
Expected: PASS (with Docker running) — including the existing round-trip / isolation tests and the new idempotency test.

- [ ] **Step 5: Commit**

```bash
git add backend/src/yieldfield/infrastructure/persistence/repositories.py backend/tests/integration/test_oltp_repositories.py
git commit -m "feat(persistence): idempotent invoice + reconciliation upsert by id (§13)"
```

---

## Task 10: Connector + jobs repository integration

**Files:**
- Create: `backend/tests/integration/test_connector_job_repositories.py`

- [ ] **Step 1: Write the failing integration tests**

Create `backend/tests/integration/test_connector_job_repositories.py`:

```python
"""Connector + Job repositories round-trip against Postgres and stay tenant-isolated (§11)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from yieldfield.domain.billing.connector import Connector, ConnectorStatus, ConnectorType
from yieldfield.domain.billing.tenant import Tenant
from yieldfield.domain.shared.ids import ConnectorId, TenantId
from yieldfield.infrastructure.persistence.job import (
    Job,
    JobResultType,
    JobStatus,
    JobType,
)
from yieldfield.infrastructure.persistence.repositories import (
    SqlAlchemyConnectorRepository,
    SqlAlchemyJobRepository,
    SqlAlchemyTenantRepository,
)


@pytest.mark.integration
def test_connector_round_trip_and_find_by_id(session: Session) -> None:
    tid = TenantId("tenant-con")
    SqlAlchemyTenantRepository(session).add(Tenant(id=tid, name="Con"))
    session.flush()
    repo = SqlAlchemyConnectorRepository(session)
    connector = Connector(
        id=ConnectorId("con_1"),
        tenant_id=tid,
        connector_type=ConnectorType.STRIPE_BILLING,
        status=ConnectorStatus.ACTIVE,
    )
    repo.add(tid, connector, b"ENCRYPTED-BLOB")
    session.flush()

    assert repo.get(tid, ConnectorId("con_1")) == connector
    assert repo.load_credentials(tid, ConnectorId("con_1")) == b"ENCRYPTED-BLOB"
    assert [c.id for c in repo.list_for_tenant(tid)] == ["con_1"]
    # find_by_id resolves the owning tenant from the id alone (webhook ingress, §6).
    assert repo.find_by_id(ConnectorId("con_1")) == connector


@pytest.mark.integration
def test_connector_reads_are_tenant_isolated(session: Session) -> None:
    tenants = SqlAlchemyTenantRepository(session)
    tenants.add(Tenant(id=TenantId("t_A"), name="A"))
    tenants.add(Tenant(id=TenantId("t_B"), name="B"))
    session.flush()
    repo = SqlAlchemyConnectorRepository(session)
    repo.add(
        TenantId("t_A"),
        Connector(
            id=ConnectorId("con_A"),
            tenant_id=TenantId("t_A"),
            connector_type=ConnectorType.STRIPE_BILLING,
        ),
        b"A-BLOB",
    )
    session.flush()
    assert repo.get(TenantId("t_B"), ConnectorId("con_A")) is None
    assert repo.list_for_tenant(TenantId("t_B")) == []


@pytest.mark.integration
def test_job_lifecycle_round_trip(session: Session) -> None:
    tid = TenantId("tenant-job")
    SqlAlchemyTenantRepository(session).add(Tenant(id=tid, name="Job"))
    session.flush()
    repo = SqlAlchemyJobRepository(session)
    job = Job(
        id="job_1",
        tenant_id=tid,
        job_type=JobType.RUN_RECONCILIATION,
        status=JobStatus.PENDING,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    repo.add(tid, job)
    session.flush()

    succeeded = Job(
        id="job_1",
        tenant_id=tid,
        job_type=JobType.RUN_RECONCILIATION,
        status=JobStatus.SUCCEEDED,
        created_at=job.created_at,
        started_at=datetime(2026, 6, 1, 0, 0, 1, tzinfo=UTC),
        finished_at=datetime(2026, 6, 1, 0, 0, 2, tzinfo=UTC),
        result_type=JobResultType.RECONCILIATION,
        result_ref="rec_1",
    )
    repo.update(tid, succeeded)
    session.flush()

    reloaded = repo.get(tid, "job_1")
    assert reloaded is not None
    assert reloaded.status is JobStatus.SUCCEEDED
    assert reloaded.result_type is JobResultType.RECONCILIATION
    assert reloaded.result_ref == "rec_1"
    # Tenant isolation: another tenant cannot read this job.
    assert repo.get(TenantId("other"), "job_1") is None
```

- [ ] **Step 2: Run to verify it passes (or skips without Docker)**

Run: `uv run pytest tests/integration/test_connector_job_repositories.py -q -m integration`
Expected: PASS (with Docker running; the session fixture migrates to head, which now includes `0002`). Without Docker — SKIP.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_connector_job_repositories.py
git commit -m "test(persistence): connector + job repo round-trips + tenant isolation (§11)"
```

---

## Task 11: ClickHouse idempotency (`ReplacingMergeTree` + `FINAL` reads)

**Files:**
- Modify: `backend/src/yieldfield/infrastructure/analytics_store/clickhouse_usage_event_store.py`
- Modify: `ops/scripts/bootstrap_clickhouse.py`
- Test: `backend/tests/integration/test_clickhouse_store.py`

- [ ] **Step 1: Write the failing dedup test**

Append to `backend/tests/integration/test_clickhouse_store.py` (reuse its existing `clickhouse_store` fixture):

```python
@pytest.mark.integration
def test_duplicate_append_is_deduped(clickhouse_store) -> None:  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime
    from decimal import Decimal

    from yieldfield.domain.billing.usage_event import UsageEvent
    from yieldfield.domain.shared.ids import TenantId, UsageEventId
    from yieldfield.domain.shared.time_window import TimeWindow

    tid = TenantId("tenant-dedup")
    event = UsageEvent(
        id=UsageEventId("meter_x:cus_1:1714521600"),
        tenant_id=tid,
        customer_id="cus_1",
        metric="api_calls",
        quantity=Decimal("5"),
        occurred_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    clickhouse_store.append(tid, [event])
    clickhouse_store.append(tid, [event])  # same id — must collapse to one row

    window = TimeWindow(datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 6, 1, tzinfo=UTC))
    rows = list(clickhouse_store.query(tid, window))
    assert len(rows) == 1
    assert rows[0].quantity == Decimal("5")
```

- [ ] **Step 2: Run to verify it fails (or skips without Docker)**

Run: `uv run pytest tests/integration/test_clickhouse_store.py::test_duplicate_append_is_deduped -q -m integration`
Expected: with Docker — FAIL (two rows under `MergeTree`). Without Docker — SKIP.

- [ ] **Step 3: Switch the engine to `ReplacingMergeTree` and read with `FINAL`**

In `backend/src/yieldfield/infrastructure/analytics_store/clickhouse_usage_event_store.py`, change the DDL `ENGINE` line in `_DDL` from `ENGINE = MergeTree` to:

```python
ENGINE = ReplacingMergeTree
```

(The existing `ORDER BY (tenant_id, occurred_at, id)` is the dedup key — appends with the same key collapse.)

Then change the `query` SQL to read `FROM {self._table} FINAL` so reads are exact without waiting for background merges. Replace the first line of the query string:

```python
            f"SELECT {', '.join(_COLUMNS)} FROM {self._table} FINAL "  # noqa: S608
```

- [ ] **Step 4: Mirror the DDL in the bootstrap script**

`ops/scripts/bootstrap_clickhouse.py` calls `ClickHouseUsageEventStore(client).ensure_schema()`, which uses the same `_DDL` constant — so the engine change in Step 3 already propagates to a freshly-bootstrapped store. No change is required in the bootstrap script; confirm by reading it that it delegates to `ensure_schema()` (it does).

- [ ] **Step 5: Run to verify it passes (full file, to confirm no regression)**

Run: `uv run pytest tests/integration/test_clickhouse_store.py -q -m integration`
Expected: PASS (with Docker running) — including the existing round-trip / window-boundary / tenant-isolation tests, which are unaffected by `FINAL` on non-duplicate data.

- [ ] **Step 6: Commit**

```bash
git add backend/src/yieldfield/infrastructure/analytics_store/clickhouse_usage_event_store.py backend/tests/integration/test_clickhouse_store.py
git commit -m "feat(analytics): ReplacingMergeTree + FINAL reads for idempotent usage ingest (§13)"
```

---

## Task 12: Connector factory

**Files:**
- Create: `backend/src/yieldfield/infrastructure/connectors/factory.py`
- Test: `backend/tests/unit/test_connector_factory.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_connector_factory.py`:

```python
"""The factory maps a Connector's type to its concrete adapter (§17)."""

from __future__ import annotations

import pytest

from yieldfield.domain.billing.connector import Connector, ConnectorType
from yieldfield.domain.shared.ids import ConnectorId, TenantId
from yieldfield.infrastructure.connectors.base.connector import ConnectorError
from yieldfield.infrastructure.connectors.factory import build_connector
from yieldfield.infrastructure.connectors.stripe_billing.connector import StripeBillingConnector


def test_build_stripe_connector() -> None:
    connector = Connector(
        id=ConnectorId("con_1"),
        tenant_id=TenantId("tenant-1"),
        connector_type=ConnectorType.STRIPE_BILLING,
    )
    live = build_connector(connector, base_url="http://stripe-mock:12111")
    assert isinstance(live, StripeBillingConnector)


def test_unsupported_type_raises() -> None:
    connector = Connector(
        id=ConnectorId("con_1"),
        tenant_id=TenantId("tenant-1"),
        connector_type=ConnectorType.STRIPE_BILLING,
    )
    # Force an unmapped value to prove the guard fires for future types.
    object.__setattr__(connector, "connector_type", "metronome")
    with pytest.raises(ConnectorError):
        build_connector(connector)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_connector_factory.py -q`
Expected: FAIL — `ModuleNotFoundError: yieldfield.infrastructure.connectors.factory`.

- [ ] **Step 3: Create the factory**

Create `backend/src/yieldfield/infrastructure/connectors/factory.py`:

```python
"""Connector factory (§17) — the one place a connector type maps to its adapter class.

Adding a platform = a new ConnectorType member + a branch here + the adapter package.
Nothing in reconciliation or the API changes. Returns an *unauthenticated* connector;
the registration service authenticates it.
"""

from __future__ import annotations

from yieldfield.domain.billing.connector import Connector, ConnectorType
from yieldfield.domain.billing.connector_port import ConnectorPort
from yieldfield.infrastructure.connectors.base.connector import ConnectorError
from yieldfield.infrastructure.connectors.stripe_billing.connector import StripeBillingConnector


def build_connector(connector: Connector, *, base_url: str | None = None) -> ConnectorPort:
    """Construct the concrete connector for `connector.connector_type` (not yet authenticated)."""
    if connector.connector_type == ConnectorType.STRIPE_BILLING:
        return StripeBillingConnector(connector.tenant_id, base_url=base_url)
    raise ConnectorError(f"Unsupported connector type: {connector.connector_type!r}.")
```

- [ ] **Step 4: Run to verify it passes + types**

Run:
```bash
uv run pytest tests/unit/test_connector_factory.py -q
uv run mypy
```
Expected: tests PASS; mypy `Success`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/yieldfield/infrastructure/connectors/factory.py backend/tests/unit/test_connector_factory.py
git commit -m "feat(connectors): factory mapping connector type to adapter (§17)"
```

---

## Task 13: Connector registration service

> This infrastructure service is the composition seam the API/workers (Plan 3C) call: it
> validates + encrypts + persists credentials on registration, and rebuilds an authenticated
> connector for ingestion/webhooks. The **application layer never touches it** (keeps
> `application ⊥ infrastructure`). It also defines the `ConnectorStore` Protocol (spec §2.1).

**Files:**
- Create: `backend/src/yieldfield/infrastructure/connectors/registration.py`
- Test: `backend/tests/unit/test_connector_registration.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_connector_registration.py`:

```python
"""Registration validates + encrypts + persists; build_authenticated round-trips (§11/§17).

authenticate() on the Stripe connector only constructs the client (no network), so these
are pure unit tests — no stripe-mock required.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from cryptography.fernet import Fernet

from yieldfield.domain.billing.connector import Connector, ConnectorType
from yieldfield.domain.shared.ids import ConnectorId, TenantId
from yieldfield.infrastructure.connectors.base.connector import ConnectorAuthError, ConnectorError
from yieldfield.infrastructure.connectors.registration import ConnectorRegistrationService
from yieldfield.infrastructure.connectors.stripe_billing.connector import StripeBillingConnector
from yieldfield.infrastructure.security.credential_cipher import FernetCredentialCipher


class FakeConnectorStore:
    def __init__(self) -> None:
        self.connectors: dict[str, Connector] = {}
        self.blobs: dict[str, bytes] = {}

    def add(
        self, tenant_id: TenantId, connector: Connector, encrypted_credentials: bytes
    ) -> None:
        self.connectors[str(connector.id)] = connector
        self.blobs[str(connector.id)] = encrypted_credentials

    def get(self, tenant_id: TenantId, connector_id: ConnectorId) -> Connector | None:
        return self.connectors.get(str(connector_id))

    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Connector]:
        return list(self.connectors.values())

    def load_credentials(self, tenant_id: TenantId, connector_id: ConnectorId) -> bytes | None:
        return self.blobs.get(str(connector_id))

    def find_by_id(self, connector_id: ConnectorId) -> Connector | None:
        return self.connectors.get(str(connector_id))


def _service(store: FakeConnectorStore) -> ConnectorRegistrationService:
    cipher = FernetCredentialCipher(Fernet.generate_key().decode())
    ids = iter(["con_1", "con_2"])
    return ConnectorRegistrationService(
        store,
        cipher,
        id_factory=lambda: ConnectorId(next(ids)),
        base_url="http://stripe-mock:12111",
    )


def test_register_encrypts_and_persists() -> None:
    store = FakeConnectorStore()
    connector = _service(store).register(
        TenantId("tenant-1"), ConnectorType.STRIPE_BILLING, {"api_key": "sk_test_1"}
    )
    assert connector.id == ConnectorId("con_1")
    # Stored blob is ciphertext, never the plaintext key.
    assert b"sk_test_1" not in store.blobs["con_1"]


def test_register_rejects_missing_required_secret() -> None:
    with pytest.raises(ConnectorAuthError):
        _service(FakeConnectorStore()).register(
            TenantId("tenant-1"), ConnectorType.STRIPE_BILLING, {}
        )


def test_build_authenticated_round_trips() -> None:
    store = FakeConnectorStore()
    service = _service(store)
    connector = service.register(
        TenantId("tenant-1"), ConnectorType.STRIPE_BILLING, {"api_key": "sk_test_1"}
    )
    live = service.build_authenticated(TenantId("tenant-1"), connector.id)
    assert isinstance(live, StripeBillingConnector)


def test_build_authenticated_unknown_connector_raises() -> None:
    with pytest.raises(ConnectorError):
        _service(FakeConnectorStore()).build_authenticated(
            TenantId("tenant-1"), ConnectorId("missing")
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_connector_registration.py -q`
Expected: FAIL — `ModuleNotFoundError: yieldfield.infrastructure.connectors.registration`.

- [ ] **Step 3: Create the registration service**

Create `backend/src/yieldfield/infrastructure/connectors/registration.py`:

```python
"""Connector registration + (re)building authenticated connectors (§11, §17).

The composition seam between stored connector config and a live connector. Registration
validates required credentials (via authenticate), encrypts them with the cipher, and
persists the config + opaque blob. `build_authenticated` reverses it for ingestion/webhooks.
Lives in infrastructure so the application layer never sees secrets or the cipher.

The `ConnectorStore` Protocol is defined here, in infrastructure — not in the domain (spec
§2.1): no inner layer depends on it, and the encrypted credential blob is not a business
concept. `SqlAlchemyConnectorRepository` (Task 6) satisfies it structurally.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Protocol, runtime_checkable
from uuid import uuid4

from yieldfield.domain.billing.connector import Connector, ConnectorStatus, ConnectorType
from yieldfield.domain.billing.connector_port import ConnectorCredentials, ConnectorPort
from yieldfield.domain.shared.ids import ConnectorId, TenantId
from yieldfield.infrastructure.connectors.base.connector import ConnectorError
from yieldfield.infrastructure.connectors.factory import build_connector
from yieldfield.infrastructure.security.credential_cipher import CredentialCipher


@runtime_checkable
class ConnectorStore(Protocol):
    """Infrastructure connector persistence, including the opaque encrypted blob (§11)."""

    def add(
        self, tenant_id: TenantId, connector: Connector, encrypted_credentials: bytes
    ) -> None: ...
    def get(self, tenant_id: TenantId, connector_id: ConnectorId) -> Connector | None: ...
    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Connector]: ...
    def load_credentials(
        self, tenant_id: TenantId, connector_id: ConnectorId
    ) -> bytes | None: ...
    def find_by_id(self, connector_id: ConnectorId) -> Connector | None: ...


def _default_id() -> ConnectorId:
    return ConnectorId(str(uuid4()))


class ConnectorRegistrationService:
    def __init__(
        self,
        store: ConnectorStore,
        cipher: CredentialCipher,
        *,
        id_factory: Callable[[], ConnectorId] = _default_id,
        base_url: str | None = None,
    ) -> None:
        self._store = store
        self._cipher = cipher
        self._id_factory = id_factory
        self._base_url = base_url

    def register(
        self, tenant_id: TenantId, connector_type: ConnectorType, secrets: Mapping[str, str]
    ) -> Connector:
        """Validate, encrypt, and persist a new connector. Raises ConnectorAuthError on
        missing required credentials (§11)."""
        connector = Connector(
            id=self._id_factory(),
            tenant_id=tenant_id,
            connector_type=connector_type,
            status=ConnectorStatus.ACTIVE,
        )
        live = build_connector(connector, base_url=self._base_url)
        live.authenticate(ConnectorCredentials(secrets=dict(secrets)))  # validates required keys
        blob = self._cipher.encrypt(secrets)
        self._store.add(tenant_id, connector, blob)
        return connector

    def build_authenticated(
        self, tenant_id: TenantId, connector_id: ConnectorId
    ) -> ConnectorPort:
        """Load + decrypt + authenticate the stored connector for ingestion/webhooks (§17)."""
        connector = self._store.get(tenant_id, connector_id)
        if connector is None:
            raise ConnectorError(
                f"Connector {connector_id!r} not found for tenant {tenant_id!r}."
            )
        blob = self._store.load_credentials(tenant_id, connector_id)
        if blob is None:
            raise ConnectorError(f"No stored credentials for connector {connector_id!r}.")
        secrets = self._cipher.decrypt(blob)
        live = build_connector(connector, base_url=self._base_url)
        live.authenticate(ConnectorCredentials(secrets=dict(secrets)))
        return live
```

- [ ] **Step 4: Run to verify it passes + types**

Run:
```bash
uv run pytest tests/unit/test_connector_registration.py -q
uv run mypy
```
Expected: tests PASS (4 passed); mypy `Success`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/yieldfield/infrastructure/connectors/registration.py backend/tests/unit/test_connector_registration.py
git commit -m "feat(connectors): registration service (validate/encrypt/persist + rebuild) + ConnectorStore port (§11/§17)"
```

---

## Task 14: Full 3A verification gate

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
Expected: ruff `All checks passed!`; black all unchanged; mypy `Success`; import-linter `Contracts: 4 kept, 0 broken.`; unit tests all PASS.

- [ ] **Step 2: Run the Docker-backed integration gate**

Ensure Docker Desktop is running, then:
```bash
uv run pytest tests/integration -q -m integration
```
Expected: PASS — including migration `0002`, idempotent invoice/reconciliation saves, connector + job repo round-trips, and ClickHouse dedup, plus the existing Slice-2 integration tests.

- [ ] **Step 3: Confirm and report**

3A is complete when all gates above are green. Report: the credential cipher, persisted `Connector` (+ store with `find_by_id`), reconciliation audit columns, the persisted `Jobs` model, idempotent OLTP/OLAP writes, and the connector factory + registration service are in place — ready for Plan 3B (application use-cases).

---

## Self-review notes (author)

- **Spec coverage (Plan 3A row, §15):** `cryptography` dep + 4th import contract + ARCHITECTURE `security/` → Task 1; config additions (spec §9) → Task 2; `CredentialCipher` → Task 3; `Connector` entity + `ConnectorId` → Task 4; reconciliation audit columns (decision C) → Task 5; `connectors` table+repo+mappers → Task 6; `jobs` table+repo+enums (spec §3, decisions E/G) → Task 7; migration `0002` → Task 8; idempotent OLTP saves (§8) → Task 9; connector+job repo integration → Task 10; ClickHouse `ReplacingMergeTree` (decision D) → Task 11; connector factory → Task 12; registration service + `ConnectorStore` (spec §2.1) → Task 13; verification → Task 14. Application use-cases, API, webhooks, workers, `run_as_job`, OpenAPI (spec §4–§7,§10) are intentionally **deferred to Plans 3B/3C**.
- **Type consistency:** `ConnectorId`, `Connector`/`ConnectorType`/`ConnectorStatus`, the infra `ConnectorStore` Protocol (`add`/`get`/`list_for_tenant`/`load_credentials`/`find_by_id`) satisfied structurally by `SqlAlchemyConnectorRepository`, `connector_row`/`to_connector`, `build_connector`, and `ConnectorRegistrationService.register`/`build_authenticated` use identical names across Tasks 4/6/12/13. `Job`/`JobType`/`JobStatus`/`JobResultType` + `SqlAlchemyJobRepository` (`add`/`get`/`update`) + `_job_row`/`_to_job` are consistent across Task 7/10. `Reconciliation` gains `executed_at`/`rule_version` in Task 5 — entity, ORM row, mappers, and all call sites in that one commit so it stays green.
- **Ordering safety:** Tasks 5–7 verify on `pytest tests/unit` only (the new columns/tables aren't in the DB until migration `0002`, Task 8). Integration tests run from Task 8 onward against a head DB that includes `0002`; the migration up/down test (Task 8) uses its own throwaway container so it never downgrades the shared `migrated_engine` database.
- **No placeholders:** every code/test step carries complete content; commands have expected output.
