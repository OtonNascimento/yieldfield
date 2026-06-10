# Slice 3C — API + Webhooks + Workers + OpenAPI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the 3A/3B money path over HTTP — tenant-scoped `/api/v1` routers, signature-routed webhooks, persisted-Job-backed Celery workers, and an OpenAPI contract with a CI drift guard — completing Slice 3's walking skeleton.

**Architecture:** Thin FastAPI adapter (validate → call a use-case → serialize) with all infrastructure composition confined to `api/v1/dependencies/` (plus the `api/webhooks/` and `workers/` composition roots). Async work runs through a `run_as_job` wrapper in `infrastructure/messaging/` that records the operational lifecycle on the OLTP `jobs` table (spec §3): RUNNING is committed in its own transaction, SUCCEEDED commits atomically with the business write, FAILED rolls back business writes first — so a failed run leaves a durable FAILED Job and no phantom financial record.

**Tech Stack:** FastAPI + Pydantic v2 (DTOs), Celery 5 (Redis broker; `send_task` by name so the API never imports task functions), SQLAlchemy 2 session-per-request, structlog, pytest + TestClient (dependency overrides) + testcontainers (E2E with `task_always_eager`).

**Branch:** `slice-3-application-api-jobs` (3A+3B tip). Governing docs: spec `docs/superpowers/specs/2026-06-02-slice-3-application-api-jobs-design.md` §3, §5–§11; `docs/PROJECT_CONTEXT.md`; `docs/ARCHITECTURE.md`.

**Run all commands from `backend/`** unless a step says otherwise.

---

## File structure (what 3C creates/modifies)

```
backend/src/yieldfield/
  api/errors/exceptions.py          NEW   API-layer typed errors (Unauthorized/IngestionDisabled/InvalidWebhookSignature)
  api/errors/handlers.py            MOD   typed exception→(status,code) map + catch-all internal_error
  api/v1/schemas/{common,connectors,ingestion,jobs,reconciliations,findings}.py  NEW  DTOs
  api/v1/dependencies/{settings,auth,pagination,database,tasks,services}.py      NEW  composition seam
  api/v1/routers/{jobs,connectors,ingestion,reconciliations,findings}.py         NEW  one file per resource
  api/v1/routers/health.py          MOD   /ready checks Postgres/ClickHouse/Redis
  api/webhooks/router.py            NEW   POST /webhooks/{connector_id}
  api/main.py                       MOD   include new routers
  infrastructure/messaging/run_as_job.py  NEW  job lifecycle wrapper (§3)
  workers/tasks.py                  NEW   3 Celery tasks (composition roots)
  config/settings.py                MOD   + connector_base_url
ops/scripts/export_openapi.py       NEW   emits contracts/openapi/openapi.json
contracts/openapi/openapi.json      NEW   committed canonical schema (§10)
.github/workflows/ci.yml            MOD   contract job becomes a real drift check
.env.example                        MOD   + YIELDFIELD_CONNECTOR_BASE_URL
backend/tests/unit/...              NEW   per-task unit tests (TestClient + fakes)
backend/tests/e2e/{conftest,test_money_path}.py  NEW  Docker E2E (integration-marked)
```

Existing surface this plan composes (verified at authoring time — implementers re-verify in pre-flight):
- 3B use-cases: `IngestInvoices(invoices).run(tenant_id, window, connector) -> int`; `IngestUsageEvents(usage_events).run(...) -> int`; `RunReconciliation(invoices, usage_events, contracts, plans, reconciliations, *, finding_id_factory=, clock=).run(tenant_id, window, reconciliation_id, rule_version=) -> Reconciliation`; `TransitionFinding(findings).run(tenant_id, finding_id, target) -> Finding`; `yieldfield.application.errors.EntityNotFoundError`.
- 3A: `Job`/`JobType`/`JobStatus`/`JobResultType` + `SqlAlchemyJobRepository(add/get/update)` (`infrastructure/persistence/job.py`, `repositories.py`); `SqlAlchemyConnectorRepository` (incl. `find_by_id`); `ConnectorRegistrationService(store, cipher, *, id_factory=, base_url=)` with `register`/`build_authenticated` + `ConnectorStore` Protocol (`infrastructure/connectors/registration.py`); `FernetCredentialCipher`/`CredentialCipherError` (`infrastructure/security/credential_cipher.py`); `create_db_engine`/`build_sessionmaker` (`persistence/engine.py`); `create_clickhouse_client` (`analytics_store/clickhouse_client.py`); `ClickHouseUsageEventStore`.
- Slice 0/2: `create_app(settings=None)` + `API_V1_PREFIX` (`api/main.py`); `_envelope(...)`/`register_error_handlers` (`api/errors/handlers.py`); `celery_app` with `task_acks_late=True` (`workers/celery_app.py`); `StripeBillingConnector` (`authenticate` requires `api_key`, optional `webhook_secret`; `verify_webhook(payload, signature) -> bool`, raises `ConnectorAuthError` when no webhook secret); `ConnectorError`/`ConnectorAuthError` (`connectors/base/connector.py`); domain errors (`InvalidFindingTransitionError`); `get_settings()` (lru_cached) with `api_tokens`/`ingestion_enabled`/`credentials_key`/`database_url`/`clickhouse_url`/`redis_url`; structlog `get_logger`.

---

## Task 1: API error surface (typed exceptions + envelope mapping)

**Files:**
- Create: `backend/src/yieldfield/api/errors/exceptions.py`
- Modify: `backend/src/yieldfield/api/errors/handlers.py`
- Test: `backend/tests/unit/test_api_error_mapping.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_api_error_mapping.py`:

```python
"""Typed exceptions map onto the standard error envelope (spec §5.4)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from yieldfield.api.errors.exceptions import (
    IngestionDisabledError,
    InvalidWebhookSignatureError,
    UnauthorizedError,
)
from yieldfield.api.errors.handlers import register_error_handlers
from yieldfield.application.errors import EntityNotFoundError
from yieldfield.domain.shared.errors import InvalidFindingTransitionError
from yieldfield.infrastructure.connectors.base.connector import ConnectorAuthError

_CASES = [
    (UnauthorizedError("Missing or invalid bearer token."), 401, "unauthorized"),
    (IngestionDisabledError("Ingestion is disabled."), 403, "ingestion_disabled"),
    (InvalidWebhookSignatureError("Bad signature."), 400, "invalid_webhook_signature"),
    (EntityNotFoundError("Finding 'f_1' not found."), 404, "not_found"),
    (InvalidFindingTransitionError("Cannot move."), 409, "invalid_finding_transition"),
    (ConnectorAuthError("Missing required credential: 'api_key'."), 400, "connector_auth_error"),
]


def _app_raising(exc: Exception) -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise exc

    return app


@pytest.mark.parametrize(("exc", "status", "code"), _CASES, ids=[c[2] for c in _CASES])
def test_typed_errors_map_to_envelope(exc: Exception, status: int, code: str) -> None:
    client = TestClient(_app_raising(exc), raise_server_exceptions=False)
    response = client.get("/boom")
    assert response.status_code == status
    body = response.json()
    assert body["error"]["code"] == code
    assert body["error"]["message"] == str(exc)


def test_unhandled_exceptions_become_internal_error_envelope() -> None:
    client = TestClient(_app_raising(ValueError("secret detail")), raise_server_exceptions=False)
    response = client.get("/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    # Internal details never leak to the client (§11).
    assert "secret detail" not in body["error"]["message"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_api_error_mapping.py -q`
Expected: FAIL — `ModuleNotFoundError: yieldfield.api.errors.exceptions`.

- [ ] **Step 3: Create the API exceptions module**

Create `backend/src/yieldfield/api/errors/exceptions.py`:

```python
"""API-layer typed errors (spec §5.4) — concerns that exist only at the HTTP boundary.

Domain/application errors (InvalidFindingTransitionError, EntityNotFoundError) are raised by
inner layers and mapped in handlers.py; these three originate in the API itself.
"""

from __future__ import annotations


class ApiError(Exception):
    """Base class for errors raised by the API adapter itself."""


class UnauthorizedError(ApiError):
    """Missing/invalid bearer token (§11) → 401 `unauthorized`."""


class IngestionDisabledError(ApiError):
    """Live-pull endpoints are feature-flagged off (§16) → 403 `ingestion_disabled`."""


class InvalidWebhookSignatureError(ApiError):
    """Inbound webhook failed signature verification (§11) → 400 `invalid_webhook_signature`."""
```

- [ ] **Step 4: Extend the handlers with the typed map + catch-all**

In `backend/src/yieldfield/api/errors/handlers.py`, replace the imports block (lines 9–17) with:

```python
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from yieldfield.api.errors.exceptions import (
    IngestionDisabledError,
    InvalidWebhookSignatureError,
    UnauthorizedError,
)
from yieldfield.application.errors import EntityNotFoundError
from yieldfield.domain.shared.errors import InvalidFindingTransitionError

# The one sanctioned infrastructure TYPE import outside dependencies/: the spec's §5.4
# mapping table names ConnectorAuthError, so the handler must reference the class. No
# composition happens here.
from yieldfield.infrastructure.connectors.base.connector import ConnectorAuthError
```

Then append after `_validation_exception_handler` (keep everything else as-is):

```python
# Typed exception → (status, code) map (spec §5.4). Message = str(exc): every mapped error
# type carries operator-safe messages (ids/keys only — never secrets, §11).
_TYPED_ERRORS: list[tuple[type[Exception], int, str]] = [
    (UnauthorizedError, status.HTTP_401_UNAUTHORIZED, "unauthorized"),
    (IngestionDisabledError, status.HTTP_403_FORBIDDEN, "ingestion_disabled"),
    (InvalidWebhookSignatureError, status.HTTP_400_BAD_REQUEST, "invalid_webhook_signature"),
    (EntityNotFoundError, status.HTTP_404_NOT_FOUND, "not_found"),
    (InvalidFindingTransitionError, status.HTTP_409_CONFLICT, "invalid_finding_transition"),
    (ConnectorAuthError, status.HTTP_400_BAD_REQUEST, "connector_auth_error"),
]


def _typed_handler(
    status_code: int, code: str
) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    async def handler(_: Request, exc: Exception) -> JSONResponse:
        return _envelope(code=code, message=str(exc), status_code=status_code)

    return handler


async def _unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    # Catch-all: every error response is enveloped (§10) and internals never leak (§11).
    return _envelope(
        code="internal_error",
        message="Internal server error.",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
```

And extend `register_error_handlers` to:

```python
def register_error_handlers(app: FastAPI) -> None:
    """Attach the envelope handlers to the app (called from the app factory)."""
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    for exc_type, status_code, code in _TYPED_ERRORS:
        app.add_exception_handler(exc_type, _typed_handler(status_code, code))
    app.add_exception_handler(Exception, _unhandled_exception_handler)
```

- [ ] **Step 5: Run to verify it passes + gates**

Run:
```bash
uv run pytest tests/unit/test_api_error_mapping.py tests/unit/test_app_health.py -q
uv run mypy
uv run ruff check . && uv run black --check .
```
Expected: 9 passed (7 new + the 2 existing health tests still green); mypy `Success`; ruff/black clean.

- [ ] **Step 6: Commit**

```bash
git add backend/src/yieldfield/api/errors/exceptions.py backend/src/yieldfield/api/errors/handlers.py backend/tests/unit/test_api_error_mapping.py
git commit -m "feat(api): typed error->envelope map + catch-all internal_error (§5.4)"
```

---

## Task 2: DTO schemas (`api/v1/schemas/`)

**Files:**
- Create: `backend/src/yieldfield/api/v1/schemas/common.py`
- Create: `backend/src/yieldfield/api/v1/schemas/connectors.py`
- Create: `backend/src/yieldfield/api/v1/schemas/ingestion.py`
- Create: `backend/src/yieldfield/api/v1/schemas/jobs.py`
- Create: `backend/src/yieldfield/api/v1/schemas/reconciliations.py`
- Create: `backend/src/yieldfield/api/v1/schemas/findings.py`
- Test: `backend/tests/unit/test_api_schemas.py`

DTOs import `yieldfield.domain` (allowed: api → domain) but never `yieldfield.infrastructure` — `JobStatusRead` uses plain `str` for job enums so schemas stay infrastructure-free; `from_job` (defined here, fed by the router) maps `.value`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_api_schemas.py`:

```python
"""DTO shapes: money-as-string precision, tz-aware windows, no secret echo (spec §5.3)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from yieldfield.api.v1.schemas.common import JobAccepted, MoneyRead, PageMeta, WindowParam
from yieldfield.api.v1.schemas.connectors import ConnectorPublic
from yieldfield.api.v1.schemas.findings import FindingRead
from yieldfield.api.v1.schemas.jobs import JobStatusRead
from yieldfield.api.v1.schemas.reconciliations import ReconciliationRead
from yieldfield.domain.billing.connector import Connector, ConnectorStatus, ConnectorType
from yieldfield.domain.findings.finding import Finding, FindingLineage
from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.severity import Severity
from yieldfield.domain.reconciliation.reconciliation import Reconciliation
from yieldfield.domain.shared.ids import ConnectorId, FindingId, ReconciliationId, TenantId
from yieldfield.domain.shared.money import Money
from yieldfield.domain.shared.time_window import TimeWindow


def test_money_serializes_amount_as_decimal_string() -> None:
    read = MoneyRead.from_money(Money(Decimal("1234.5600"), "USD"))
    assert read.amount == "1234.5600"  # NUMERIC precision preserved across JSON (§7)
    assert read.currency == "USD"
    assert isinstance(read.model_dump()["amount"], str)


def test_window_param_rejects_naive_datetimes() -> None:
    with pytest.raises(ValidationError):
        WindowParam(start=datetime(2026, 1, 1), end=datetime(2026, 2, 1, tzinfo=UTC))


def test_window_param_rejects_end_before_start() -> None:
    with pytest.raises(ValidationError):
        WindowParam(
            start=datetime(2026, 2, 1, tzinfo=UTC), end=datetime(2026, 1, 1, tzinfo=UTC)
        )


def test_window_param_round_trips_to_domain_window() -> None:
    param = WindowParam(
        start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 2, 1, tzinfo=UTC)
    )
    window = param.to_window()
    assert isinstance(window, TimeWindow)
    assert window.start == param.start and window.end == param.end


def test_connector_public_never_carries_secrets() -> None:
    connector = Connector(
        id=ConnectorId("con_1"),
        tenant_id=TenantId("t_1"),
        connector_type=ConnectorType.STRIPE_BILLING,
        status=ConnectorStatus.ACTIVE,
    )
    public = ConnectorPublic.from_connector(connector)
    assert set(public.model_dump()) == {"id", "connector_type", "status"}  # no secrets field


def test_finding_and_reconciliation_reads_expose_dollars_and_explanations() -> None:
    finding = Finding(
        id=FindingId("f_1"),
        tenant_id=TenantId("t_1"),
        reconciliation_id=ReconciliationId("r_1"),
        customer_id="cus_1",
        metric="api_calls",
        leakage_type=LeakageType.UNBILLED_USAGE,
        severity=Severity.LOW,
        amount=Money.of("10.00", "USD"),
        status=RecoveryStatus.NEW,
        lineage=FindingLineage(rule_version="reconciliation-v1"),
        explanation="100 api_calls were not billed.",
    )
    recon = Reconciliation(
        id=ReconciliationId("r_1"),
        tenant_id=TenantId("t_1"),
        window=TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)),
        currency="USD",
        executed_at=datetime(2026, 3, 1, tzinfo=UTC),
        rule_version="reconciliation-v1",
        findings=(finding,),
    )
    fr = FindingRead.from_finding(finding)
    assert fr.amount.amount == "10.00"
    assert fr.explanation == "100 api_calls were not billed."
    assert "lineage" not in fr.model_dump()  # internal lineage stays internal (§5.3)
    rr = ReconciliationRead.from_reconciliation(recon)
    assert rr.total_leakage.amount == "10.00"
    assert rr.finding_count == 1
    assert rr.rule_version == "reconciliation-v1"


def test_job_status_read_maps_optional_result_pair() -> None:
    base = {
        "job_id": "job_1",
        "job_type": "run_reconciliation",
        "status": "succeeded",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    read = JobStatusRead(**base, result_type="reconciliation", result_ref="rec_1")
    assert read.result_ref == "rec_1"
    pending = JobStatusRead(**{**base, "status": "pending"})
    assert pending.result_type is None and pending.error is None
    assert PageMeta().next_cursor is None
    assert JobAccepted(job_id="job_1").job_id == "job_1"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_api_schemas.py -q`
Expected: FAIL — `ModuleNotFoundError: yieldfield.api.v1.schemas.common`.

- [ ] **Step 3: Create the schema modules**

Create `backend/src/yieldfield/api/v1/schemas/common.py`:

```python
"""Shared DTO primitives (spec §5.3): money-as-string, windows, pagination, job handles."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator, model_validator

from yieldfield.domain.shared.money import Money
from yieldfield.domain.shared.time_window import TimeWindow


class MoneyRead(BaseModel):
    """Money over JSON: a decimal STRING amount — floats never touch money (§7)."""

    amount: str
    currency: str

    @classmethod
    def from_money(cls, money: Money) -> MoneyRead:
        return cls(amount=str(money.amount), currency=money.currency)


class WindowRead(BaseModel):
    start: datetime
    end: datetime

    @classmethod
    def from_window(cls, window: TimeWindow) -> WindowRead:
        return cls(start=window.start, end=window.end)


class WindowParam(BaseModel):
    """Inbound window: validated at the boundary (422) before touching the domain."""

    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def _tz_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("must be timezone-aware (ISO-8601 with offset)")
        return value

    @model_validator(mode="after")
    def _ordered(self) -> WindowParam:
        if self.end < self.start:
            raise ValueError("end must not be before start")
        return self

    def to_window(self) -> TimeWindow:
        return TimeWindow(self.start, self.end)


class PageMeta(BaseModel):
    """Opaque-cursor pagination metadata (§10). `next_cursor=None` means last page."""

    next_cursor: str | None = None


class JobAccepted(BaseModel):
    """The 202 handle every async POST returns (spec §3)."""

    job_id: str
```

Create `backend/src/yieldfield/api/v1/schemas/connectors.py`:

```python
"""Connector DTOs (spec §5.2/§5.3). Secrets go in, NEVER come back out (§11)."""

from __future__ import annotations

from pydantic import BaseModel

from yieldfield.api.v1.schemas.common import PageMeta
from yieldfield.domain.billing.connector import Connector, ConnectorStatus, ConnectorType


class ConnectorCreate(BaseModel):
    connector_type: ConnectorType
    secrets: dict[str, str]


class ConnectorPublic(BaseModel):
    """The only connector shape the API returns — id/type/status, no credentials (§11)."""

    id: str
    connector_type: ConnectorType
    status: ConnectorStatus

    @classmethod
    def from_connector(cls, connector: Connector) -> ConnectorPublic:
        return cls(
            id=str(connector.id),
            connector_type=connector.connector_type,
            status=connector.status,
        )


class ConnectorPage(BaseModel):
    items: list[ConnectorPublic]
    meta: PageMeta
```

Create `backend/src/yieldfield/api/v1/schemas/ingestion.py`:

```python
"""Ingestion trigger DTO (spec §5.2): which connector, which window."""

from __future__ import annotations

from pydantic import BaseModel

from yieldfield.api.v1.schemas.common import WindowParam


class IngestionRequest(BaseModel):
    connector_id: str
    window: WindowParam
```

Create `backend/src/yieldfield/api/v1/schemas/jobs.py`:

```python
"""Job status DTO (spec §5.2) — the poll surface for all async operations.

Plain `str` enums keep schemas infrastructure-free (the Job enums live in
infrastructure/persistence); routers map `.value` when building this DTO.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class JobStatusRead(BaseModel):
    job_id: str
    job_type: str
    status: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    result_type: str | None = None
    result_ref: str | None = None
```

Create `backend/src/yieldfield/api/v1/schemas/reconciliations.py`:

```python
"""Reconciliation DTOs (spec §5.2/§5.3): the financial-audit read surface."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from yieldfield.api.v1.schemas.common import MoneyRead, PageMeta, WindowParam, WindowRead
from yieldfield.domain.reconciliation.reconciliation import Reconciliation


class ReconciliationCreate(BaseModel):
    window: WindowParam


class ReconciliationRead(BaseModel):
    id: str
    window: WindowRead
    currency: str
    executed_at: datetime
    rule_version: str
    total_leakage: MoneyRead
    finding_count: int

    @classmethod
    def from_reconciliation(cls, reconciliation: Reconciliation) -> ReconciliationRead:
        return cls(
            id=str(reconciliation.id),
            window=WindowRead.from_window(reconciliation.window),
            currency=reconciliation.currency,
            executed_at=reconciliation.executed_at,
            rule_version=reconciliation.rule_version,
            total_leakage=MoneyRead.from_money(reconciliation.total_leakage()),
            finding_count=reconciliation.finding_count,
        )


class ReconciliationPage(BaseModel):
    items: list[ReconciliationRead]
    meta: PageMeta
```

Create `backend/src/yieldfield/api/v1/schemas/findings.py`:

```python
"""Finding DTOs (spec §5.3): dollars + explanations out; internal lineage stays in (§2)."""

from __future__ import annotations

from pydantic import BaseModel

from yieldfield.api.v1.schemas.common import MoneyRead, PageMeta
from yieldfield.domain.findings.finding import Finding
from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.severity import Severity


class FindingRead(BaseModel):
    id: str
    reconciliation_id: str
    customer_id: str
    metric: str
    leakage_type: LeakageType
    severity: Severity
    status: RecoveryStatus
    amount: MoneyRead
    explanation: str

    @classmethod
    def from_finding(cls, finding: Finding) -> FindingRead:
        return cls(
            id=str(finding.id),
            reconciliation_id=str(finding.reconciliation_id),
            customer_id=finding.customer_id,
            metric=finding.metric,
            leakage_type=finding.leakage_type,
            severity=finding.severity,
            status=finding.status,
            amount=MoneyRead.from_money(finding.amount),
            explanation=finding.explanation,
        )


class FindingPage(BaseModel):
    items: list[FindingRead]
    meta: PageMeta
```

- [ ] **Step 4: Run to verify it passes + types**

Run:
```bash
uv run pytest tests/unit/test_api_schemas.py -q
uv run mypy
```
Expected: 7 passed; mypy `Success`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/yieldfield/api/v1/schemas backend/tests/unit/test_api_schemas.py
git commit -m "feat(api): request/response DTOs - money strings, windows, pages (§5.3)"
```

---

## Task 3: Request dependencies (auth, pagination, session, task queue, services)

**Files:**
- Create: `backend/src/yieldfield/api/v1/dependencies/settings.py`
- Create: `backend/src/yieldfield/api/v1/dependencies/auth.py`
- Create: `backend/src/yieldfield/api/v1/dependencies/pagination.py`
- Create: `backend/src/yieldfield/api/v1/dependencies/database.py`
- Create: `backend/src/yieldfield/api/v1/dependencies/tasks.py`
- Create: `backend/src/yieldfield/api/v1/dependencies/services.py`
- Modify: `backend/src/yieldfield/config/settings.py` (add `connector_base_url`)
- Modify: `.env.example` (repo root — add `YIELDFIELD_CONNECTOR_BASE_URL`)
- Test: `backend/tests/unit/test_api_dependencies.py`; Modify: `backend/tests/unit/test_settings.py`

This is the ONLY API package permitted to import infrastructure (spec §5; composition seam). Routers import the `Annotated` aliases defined here and never name infrastructure modules.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_api_dependencies.py`:

```python
"""Auth resolves tenants from bearer tokens; cursors are opaque and bounded (spec §5.1)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from yieldfield.api.errors.exceptions import UnauthorizedError
from yieldfield.api.v1.dependencies.auth import current_tenant
from yieldfield.api.v1.dependencies.pagination import (
    PageParams,
    decode_cursor,
    encode_cursor,
    paginate,
)
from yieldfield.config.settings import Settings
from yieldfield.domain.shared.ids import TenantId


def _settings() -> Settings:
    return Settings(_env_file=None, api_tokens={"tok-1": "tenant-1"})


def test_current_tenant_resolves_token_to_tenant() -> None:
    assert current_tenant(_settings(), authorization="Bearer tok-1") == TenantId("tenant-1")


def test_current_tenant_rejects_missing_header() -> None:
    with pytest.raises(UnauthorizedError):
        current_tenant(_settings(), authorization=None)


def test_current_tenant_rejects_non_bearer_scheme() -> None:
    with pytest.raises(UnauthorizedError):
        current_tenant(_settings(), authorization="Basic tok-1")


def test_current_tenant_rejects_unknown_token() -> None:
    with pytest.raises(UnauthorizedError):
        current_tenant(_settings(), authorization="Bearer nope")


def test_cursor_round_trips_and_is_opaque() -> None:
    cursor = encode_cursor(150)
    assert cursor != "150"  # opaque, not a bare offset (§10)
    assert decode_cursor(cursor) == 150


def test_garbage_cursor_is_a_400() -> None:
    with pytest.raises(HTTPException) as excinfo:
        decode_cursor("not-a-cursor")
    assert excinfo.value.status_code == 400


def test_paginate_slices_and_signals_the_last_page() -> None:
    items = list(range(10))
    first, cursor = paginate(items, PageParams(limit=4, offset=0))
    assert first == [0, 1, 2, 3] and cursor is not None
    middle, cursor2 = paginate(items, PageParams(limit=4, offset=decode_cursor(cursor)))
    assert middle == [4, 5, 6, 7] and cursor2 is not None
    last, end = paginate(items, PageParams(limit=4, offset=decode_cursor(cursor2)))
    assert last == [8, 9] and end is None
```

Append to `backend/tests/unit/test_settings.py`:

```python
def test_connector_base_url_defaults_to_none() -> None:
    settings = Settings(_env_file=None)
    assert settings.connector_base_url is None
```

(If that file's existing tests build `Settings` differently — e.g. via `monkeypatch.setenv` — match its local idiom; the assertion is what matters.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_api_dependencies.py -q`
Expected: FAIL — `ModuleNotFoundError: yieldfield.api.v1.dependencies.auth`.

- [ ] **Step 3: Add the setting**

In `backend/src/yieldfield/config/settings.py`, inside the `# ── Connector credentials & auth` block after `ingestion_enabled: bool = False`, add:

```python
    # Optional base-URL override for billing-platform connectors (stripe-mock in tests/CI;
    # unset in production so connectors hit the real platform) (§16, §17).
    connector_base_url: str | None = None
```

In `.env.example` (repo root), after the `YIELDFIELD_INGESTION_ENABLED=false` line, add:

```
# Optional connector base-URL override (point at stripe-mock locally; leave unset for live).
YIELDFIELD_CONNECTOR_BASE_URL=
```

- [ ] **Step 4: Create the dependency modules**

Create `backend/src/yieldfield/api/v1/dependencies/settings.py`:

```python
"""Settings as a FastAPI dependency — one override point for every test (§16)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from yieldfield.config.settings import Settings, get_settings


def get_app_settings() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
```

Create `backend/src/yieldfield/api/v1/dependencies/auth.py`:

```python
"""Bearer-token → tenant resolution (spec §5.1, §11).

Config-driven (`api_tokens`: token → tenant_id) so an OIDC validator can replace this
dependency later without touching any router. Every tenant-scoped route depends on
`CurrentTenant`; no endpoint ever accepts a tenant_id from the client.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header

from yieldfield.api.errors.exceptions import UnauthorizedError
from yieldfield.api.v1.dependencies.settings import SettingsDep
from yieldfield.domain.shared.ids import TenantId

_BEARER_PREFIX = "Bearer "


def current_tenant(
    settings: SettingsDep,
    authorization: Annotated[str | None, Header()] = None,
) -> TenantId:
    if not authorization or not authorization.startswith(_BEARER_PREFIX):
        raise UnauthorizedError("Missing or invalid bearer token.")
    token = authorization.removeprefix(_BEARER_PREFIX).strip()
    tenant_id = settings.api_tokens.get(token)
    if tenant_id is None:
        raise UnauthorizedError("Missing or invalid bearer token.")
    return TenantId(tenant_id)


CurrentTenant = Annotated[TenantId, Depends(current_tenant)]
```

Create `backend/src/yieldfield/api/v1/dependencies/pagination.py`:

```python
"""Bounded-limit, opaque-cursor pagination (spec §5.1, §10).

The wire contract is cursor-based (stable for the Slice-4 client). Internally the cursor
encodes an offset over the repository's full listing — a named simplification: the 3A
repositories expose `list_*` without keyset queries. Swapping to keyset pagination later
changes only this module, not the API contract.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, TypeVar

from fastapi import Depends, HTTPException, Query, status

T = TypeVar("T")

_PREFIX = "o:"


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"{_PREFIX}{offset}".encode()).decode()


def decode_cursor(cursor: str) -> int:
    try:
        text = base64.urlsafe_b64decode(cursor.encode()).decode()
        if not text.startswith(_PREFIX):
            raise ValueError(text)
        offset = int(text.removeprefix(_PREFIX))
        if offset < 0:
            raise ValueError(text)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid pagination cursor."
        ) from exc
    return offset


@dataclass(frozen=True, slots=True)
class PageParams:
    limit: int
    offset: int


def page_params(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> PageParams:
    return PageParams(limit=limit, offset=decode_cursor(cursor) if cursor else 0)


PageParamsDep = Annotated[PageParams, Depends(page_params)]


def paginate(items: Sequence[T], page: PageParams) -> tuple[list[T], str | None]:
    """Slice one page; return (items, next_cursor) with next_cursor=None on the last page."""
    window = list(items[page.offset : page.offset + page.limit])
    has_more = page.offset + page.limit < len(items)
    return window, encode_cursor(page.offset + page.limit) if has_more else None
```

Create `backend/src/yieldfield/api/v1/dependencies/database.py`:

```python
"""Request-scoped OLTP session (spec §5.1): commit on success, rollback on error, always close."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session, sessionmaker

from yieldfield.config.settings import get_settings
from yieldfield.infrastructure.persistence.engine import build_sessionmaker, create_db_engine


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    """One engine per process, built lazily so importing the app needs no database (§16)."""
    return build_sessionmaker(create_db_engine(get_settings().database_url))


def db_session() -> Iterator[Session]:
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


DbSession = Annotated[Session, Depends(db_session)]
```

Create `backend/src/yieldfield/api/v1/dependencies/tasks.py`:

```python
"""Task-queue seam (spec §7): the API enqueues Celery tasks BY NAME via `send_task`,
so it never imports task functions — and tests fake this Protocol instead of a broker."""

from __future__ import annotations

from typing import Annotated, Protocol, cast

from fastapi import Depends


class TaskQueue(Protocol):
    def enqueue(self, task_name: str, *args: str) -> str:
        """Queue `task_name` with string args; return the broker task id."""
        ...


class CeleryTaskQueue:
    def enqueue(self, task_name: str, *args: str) -> str:
        # Deferred import: broker config is read at enqueue time, not at app import.
        from yieldfield.workers.celery_app import celery_app

        return cast(str, celery_app.send_task(task_name, args=list(args)).id)


def get_task_queue() -> TaskQueue:
    return CeleryTaskQueue()


TaskQueueDep = Annotated[TaskQueue, Depends(get_task_queue)]
```

Create `backend/src/yieldfield/api/v1/dependencies/services.py`:

```python
"""Composition of 3A adapters for request handling (spec §5.1) — the only place API code
builds repositories, the cipher, or the registration service. Routers consume the
Annotated aliases and never import infrastructure themselves.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from yieldfield.api.v1.dependencies.database import DbSession
from yieldfield.api.v1.dependencies.settings import SettingsDep
from yieldfield.config.settings import Settings
from yieldfield.infrastructure.connectors.registration import ConnectorRegistrationService
from yieldfield.infrastructure.persistence.repositories import (
    SqlAlchemyConnectorRepository,
    SqlAlchemyFindingRepository,
    SqlAlchemyJobRepository,
    SqlAlchemyReconciliationRepository,
)
from yieldfield.infrastructure.security.credential_cipher import (
    CredentialCipherError,
    FernetCredentialCipher,
)


def get_job_repository(session: DbSession) -> SqlAlchemyJobRepository:
    return SqlAlchemyJobRepository(session)


def get_connector_store(session: DbSession) -> SqlAlchemyConnectorRepository:
    return SqlAlchemyConnectorRepository(session)


def get_finding_repository(session: DbSession) -> SqlAlchemyFindingRepository:
    return SqlAlchemyFindingRepository(session)


def get_reconciliation_repository(session: DbSession) -> SqlAlchemyReconciliationRepository:
    return SqlAlchemyReconciliationRepository(session)


def _cipher(settings: Settings) -> FernetCredentialCipher:
    if not settings.credentials_key:
        raise CredentialCipherError(
            "YIELDFIELD_CREDENTIALS_KEY is required to register or use connectors (§16)."
        )
    return FernetCredentialCipher(settings.credentials_key)


def get_registration_service(
    session: DbSession, settings: SettingsDep
) -> ConnectorRegistrationService:
    return ConnectorRegistrationService(
        SqlAlchemyConnectorRepository(session),
        _cipher(settings),
        base_url=settings.connector_base_url,
    )


JobRepo = Annotated[SqlAlchemyJobRepository, Depends(get_job_repository)]
ConnectorStoreDep = Annotated[SqlAlchemyConnectorRepository, Depends(get_connector_store)]
FindingRepo = Annotated[SqlAlchemyFindingRepository, Depends(get_finding_repository)]
ReconciliationRepo = Annotated[
    SqlAlchemyReconciliationRepository, Depends(get_reconciliation_repository)
]
RegistrationDep = Annotated[ConnectorRegistrationService, Depends(get_registration_service)]
```

- [ ] **Step 5: Run to verify it passes + gates**

Run:
```bash
uv run pytest tests/unit/test_api_dependencies.py tests/unit/test_settings.py -q
uv run mypy
uv run lint-imports
uv run ruff check . && uv run black --check .
```
Expected: dependencies 7 passed + settings suite green (1 new test); mypy `Success`; `Contracts: 4 kept, 0 broken.`; ruff/black clean.

- [ ] **Step 6: Commit**

```bash
git add backend/src/yieldfield/api/v1/dependencies backend/src/yieldfield/config/settings.py .env.example backend/tests/unit/test_api_dependencies.py backend/tests/unit/test_settings.py
git commit -m "feat(api): auth/pagination/session/task-queue/service dependencies (§5.1)"
```

---

## Task 4: Jobs router — `GET /api/v1/jobs/{job_id}`

> First real router: establishes the test pattern every later router task reuses —
> `create_app()` + `app.dependency_overrides` on the dependency FUNCTIONS (not the aliases),
> auth via `{"Authorization": "Bearer tok-1"}`.

**Files:**
- Create: `backend/src/yieldfield/api/v1/routers/jobs.py`
- Modify: `backend/src/yieldfield/api/v1/dependencies/services.py` (add `job_status_read`)
- Modify: `backend/src/yieldfield/api/main.py` (include router)
- Test: `backend/tests/unit/test_jobs_router.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_jobs_router.py`:

```python
"""GET /jobs/{id}: the OLTP-backed poll surface for async work (spec §5.2)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from yieldfield.api.main import create_app
from yieldfield.api.v1.dependencies.services import get_job_repository
from yieldfield.api.v1.dependencies.settings import get_app_settings
from yieldfield.config.settings import Settings
from yieldfield.domain.shared.ids import TenantId
from yieldfield.infrastructure.persistence.job import Job, JobResultType, JobStatus, JobType

AUTH = {"Authorization": "Bearer tok-1"}


def _settings() -> Settings:
    return Settings(_env_file=None, api_tokens={"tok-1": "tenant-1"})


class FakeJobRepo:
    def __init__(self, job: Job | None) -> None:
        self._job = job

    def get(self, tenant_id: TenantId, job_id: str) -> Job | None:
        if self._job is not None and self._job.id == job_id and self._job.tenant_id == tenant_id:
            return self._job
        return None


def _app(job: Job | None) -> FastAPI:
    app = create_app(_settings())
    app.dependency_overrides[get_app_settings] = _settings
    app.dependency_overrides[get_job_repository] = lambda: FakeJobRepo(job)
    return app


def _job() -> Job:
    return Job(
        id="job_1",
        tenant_id=TenantId("tenant-1"),
        job_type=JobType.RUN_RECONCILIATION,
        status=JobStatus.SUCCEEDED,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
        started_at=datetime(2026, 6, 1, 0, 0, 1, tzinfo=UTC),
        finished_at=datetime(2026, 6, 1, 0, 0, 2, tzinfo=UTC),
        result_type=JobResultType.RECONCILIATION,
        result_ref="rec_1",
    )


def test_get_job_returns_status_and_result_pair() -> None:
    client = TestClient(_app(_job()))
    response = client.get("/api/v1/jobs/job_1", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == "job_1"
    assert body["job_type"] == "run_reconciliation"
    assert body["status"] == "succeeded"
    assert body["result_type"] == "reconciliation"
    assert body["result_ref"] == "rec_1"
    assert body["error"] is None


def test_missing_job_is_404_enveloped() -> None:
    client = TestClient(_app(None))
    response = client.get("/api/v1/jobs/nope", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_jobs_require_bearer_auth() -> None:
    client = TestClient(_app(_job()))
    assert client.get("/api/v1/jobs/job_1").status_code == 401
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_jobs_router.py -q`
Expected: FAIL — `ModuleNotFoundError: yieldfield.api.v1.routers.jobs` (the import inside `main.py` change comes in Step 3; the test file itself fails on importing the router module via `create_app` only after wiring — first failure is the bare 404 because the route doesn't exist; either failure mode is acceptable as RED).

- [ ] **Step 3: Add the Job→DTO mapper to services and create the router**

Append to `backend/src/yieldfield/api/v1/dependencies/services.py` (it already imports the infrastructure Job types' home module — add `Job` to that import and `JobStatusRead` to the imports):

```python
from yieldfield.api.v1.schemas.jobs import JobStatusRead
from yieldfield.infrastructure.persistence.job import Job
```

and the mapper function at the end of the file:

```python
def job_status_read(job: Job) -> JobStatusRead:
    """Map the infrastructure Job onto the DTO here so routers never import infrastructure."""
    return JobStatusRead(
        job_id=job.id,
        job_type=job.job_type.value,
        status=job.status.value,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        error=job.error,
        result_type=job.result_type.value if job.result_type is not None else None,
        result_ref=job.result_ref,
    )
```

Create `backend/src/yieldfield/api/v1/routers/jobs.py`:

```python
"""GET /jobs/{job_id} (spec §5.2) — the authoritative, OLTP-backed async-status surface (§3).

Thin adapter: resolve tenant, read the Job, serialize. On SUCCEEDED the client follows
`result_ref` (e.g. to GET /reconciliations/{id}); failures surface here as FAILED + error.
"""

from __future__ import annotations

from fastapi import APIRouter

from yieldfield.api.v1.dependencies.auth import CurrentTenant
from yieldfield.api.v1.dependencies.services import JobRepo, job_status_read
from yieldfield.api.v1.schemas.jobs import JobStatusRead
from yieldfield.application.errors import EntityNotFoundError

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", summary="Poll an async job", response_model=JobStatusRead)
def get_job(job_id: str, tenant_id: CurrentTenant, jobs: JobRepo) -> JobStatusRead:
    job = jobs.get(tenant_id, job_id)
    if job is None:
        raise EntityNotFoundError(f"Job {job_id!r} not found.")
    return job_status_read(job)
```

In `backend/src/yieldfield/api/main.py`, change the routers import line to:

```python
from yieldfield.api.v1.routers import health, jobs
```

and after the existing `app.include_router(health.router, prefix=API_V1_PREFIX)` add:

```python
    app.include_router(jobs.router, prefix=API_V1_PREFIX)
```

- [ ] **Step 4: Run to verify it passes + gates**

Run:
```bash
uv run pytest tests/unit/test_jobs_router.py tests/unit/test_app_health.py -q
uv run mypy
```
Expected: 5 passed; mypy `Success`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/yieldfield/api/v1/routers/jobs.py backend/src/yieldfield/api/v1/dependencies/services.py backend/src/yieldfield/api/main.py backend/tests/unit/test_jobs_router.py
git commit -m "feat(api): GET /jobs/{id} - durable async-status poll surface (§3/§5.2)"
```

---

## Task 5: Connectors router — `POST /connectors`, `GET /connectors`

**Files:**
- Create: `backend/src/yieldfield/api/v1/routers/connectors.py`
- Modify: `backend/src/yieldfield/api/main.py` (include router)
- Test: `backend/tests/unit/test_connectors_router.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_connectors_router.py`:

```python
"""POST/GET /connectors: register validates creds; responses never carry secrets (§11)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from fastapi import FastAPI
from fastapi.testclient import TestClient

from yieldfield.api.main import create_app
from yieldfield.api.v1.dependencies.services import get_connector_store, get_registration_service
from yieldfield.api.v1.dependencies.settings import get_app_settings
from yieldfield.config.settings import Settings
from yieldfield.domain.billing.connector import Connector, ConnectorStatus, ConnectorType
from yieldfield.domain.shared.ids import ConnectorId, TenantId
from yieldfield.infrastructure.connectors.base.connector import ConnectorAuthError

AUTH = {"Authorization": "Bearer tok-1"}


def _settings() -> Settings:
    return Settings(_env_file=None, api_tokens={"tok-1": "tenant-1"})


def _connector(connector_id: str = "con_1") -> Connector:
    return Connector(
        id=ConnectorId(connector_id),
        tenant_id=TenantId("tenant-1"),
        connector_type=ConnectorType.STRIPE_BILLING,
        status=ConnectorStatus.ACTIVE,
    )


class FakeRegistration:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[TenantId, ConnectorType, Mapping[str, str]]] = []

    def register(
        self, tenant_id: TenantId, connector_type: ConnectorType, secrets: Mapping[str, str]
    ) -> Connector:
        self.calls.append((tenant_id, connector_type, secrets))
        if self.fail:
            raise ConnectorAuthError("Missing required credential: 'api_key'.")
        return _connector()


class FakeStore:
    def __init__(self, connectors: Sequence[Connector]) -> None:
        self._connectors = connectors

    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Connector]:
        return list(self._connectors)


def _app(registration: FakeRegistration, store: FakeStore | None = None) -> FastAPI:
    app = create_app(_settings())
    app.dependency_overrides[get_app_settings] = _settings
    app.dependency_overrides[get_registration_service] = lambda: registration
    app.dependency_overrides[get_connector_store] = lambda: store or FakeStore([])
    return app


def test_register_returns_201_public_shape_and_no_secrets() -> None:
    registration = FakeRegistration()
    client = TestClient(_app(registration))
    response = client.post(
        "/api/v1/connectors",
        headers=AUTH,
        json={"connector_type": "stripe_billing", "secrets": {"api_key": "sk_test_1"}},
    )
    assert response.status_code == 201
    body = response.json()
    assert body == {"id": "con_1", "connector_type": "stripe_billing", "status": "active"}
    assert "sk_test_1" not in response.text  # the secret never round-trips (§11)
    assert registration.calls[0][0] == TenantId("tenant-1")  # tenant from the token, not the body


def test_register_with_bad_credentials_is_400_connector_auth_error() -> None:
    client = TestClient(_app(FakeRegistration(fail=True)))
    response = client.post(
        "/api/v1/connectors",
        headers=AUTH,
        json={"connector_type": "stripe_billing", "secrets": {}},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "connector_auth_error"


def test_list_connectors_paginates() -> None:
    store = FakeStore([_connector(f"con_{i}") for i in range(3)])
    client = TestClient(_app(FakeRegistration(), store))
    response = client.get("/api/v1/connectors?limit=2", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert [c["id"] for c in body["items"]] == ["con_0", "con_1"]
    assert body["meta"]["next_cursor"] is not None
    response2 = client.get(
        f"/api/v1/connectors?limit=2&cursor={body['meta']['next_cursor']}", headers=AUTH
    )
    assert [c["id"] for c in response2.json()["items"]] == ["con_2"]
    assert response2.json()["meta"]["next_cursor"] is None


def test_unknown_connector_type_is_422() -> None:
    client = TestClient(_app(FakeRegistration()))
    response = client.post(
        "/api/v1/connectors",
        headers=AUTH,
        json={"connector_type": "metronome", "secrets": {}},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_connectors_require_bearer_auth() -> None:
    client = TestClient(_app(FakeRegistration()))
    assert client.get("/api/v1/connectors").status_code == 401
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_connectors_router.py -q`
Expected: FAIL — 404s (routes don't exist yet).

- [ ] **Step 3: Create the router and wire it**

Create `backend/src/yieldfield/api/v1/routers/connectors.py`:

```python
"""POST/GET /connectors (spec §5.2): register (validate→encrypt→persist) and list.

The tenant comes from the bearer token, never the body (§11). Registration delegates to
the infrastructure ConnectorRegistrationService via its dependency; bad credentials raise
ConnectorAuthError → 400 `connector_auth_error` (spec §5.4). Update/delete/OAuth are
out of scope this slice (spec §0).
"""

from __future__ import annotations

from fastapi import APIRouter, status

from yieldfield.api.v1.dependencies.auth import CurrentTenant
from yieldfield.api.v1.dependencies.pagination import PageParamsDep, paginate
from yieldfield.api.v1.dependencies.services import ConnectorStoreDep, RegistrationDep
from yieldfield.api.v1.schemas.common import PageMeta
from yieldfield.api.v1.schemas.connectors import ConnectorCreate, ConnectorPage, ConnectorPublic

router = APIRouter(prefix="/connectors", tags=["connectors"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Register a billing-platform connector",
    response_model=ConnectorPublic,
)
def register_connector(
    body: ConnectorCreate, tenant_id: CurrentTenant, registration: RegistrationDep
) -> ConnectorPublic:
    connector = registration.register(tenant_id, body.connector_type, body.secrets)
    return ConnectorPublic.from_connector(connector)


@router.get("", summary="List the tenant's connectors", response_model=ConnectorPage)
def list_connectors(
    tenant_id: CurrentTenant, store: ConnectorStoreDep, page: PageParamsDep
) -> ConnectorPage:
    items, next_cursor = paginate(store.list_for_tenant(tenant_id), page)
    return ConnectorPage(
        items=[ConnectorPublic.from_connector(c) for c in items],
        meta=PageMeta(next_cursor=next_cursor),
    )
```

In `backend/src/yieldfield/api/main.py`, extend the routers import to `from yieldfield.api.v1.routers import connectors, health, jobs` and add `app.include_router(connectors.router, prefix=API_V1_PREFIX)` after the jobs line.

- [ ] **Step 4: Run to verify it passes + gates**

Run:
```bash
uv run pytest tests/unit/test_connectors_router.py -q
uv run mypy
```
Expected: 5 passed; mypy `Success`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/yieldfield/api/v1/routers/connectors.py backend/src/yieldfield/api/main.py backend/tests/unit/test_connectors_router.py
git commit -m "feat(api): connector register/list - secrets in, never out (§5.2/§11)"
```

---

## Task 6: Job submission seam + ingestion router — `POST /ingestion/{invoices,usage-events}` → 202

**Files:**
- Modify: `backend/src/yieldfield/api/v1/dependencies/services.py` (add task-name constants + `JobSubmitter`)
- Create: `backend/src/yieldfield/api/v1/routers/ingestion.py`
- Modify: `backend/src/yieldfield/api/main.py` (include router)
- Test: `backend/tests/unit/test_ingestion_router.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_ingestion_router.py`:

```python
"""POST /ingestion/*: flag-gated 202s that persist a PENDING Job BEFORE enqueueing (§3, §16)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from yieldfield.api.main import create_app
from yieldfield.api.v1.dependencies.services import (
    INGEST_INVOICES_TASK,
    INGEST_USAGE_EVENTS_TASK,
    JobSubmitter,
    get_job_submitter,
)
from yieldfield.api.v1.dependencies.settings import get_app_settings
from yieldfield.config.settings import Settings
from yieldfield.domain.shared.ids import TenantId
from yieldfield.infrastructure.persistence.job import Job, JobStatus, JobType

AUTH = {"Authorization": "Bearer tok-1"}
WINDOW_JSON = {"start": "2026-01-01T00:00:00+00:00", "end": "2026-02-01T00:00:00+00:00"}


def _settings(*, enabled: bool = True) -> Settings:
    return Settings(_env_file=None, api_tokens={"tok-1": "tenant-1"}, ingestion_enabled=enabled)


class FakeSubmitter:
    def __init__(self) -> None:
        self.submitted: list[tuple[TenantId, str, tuple[str, ...]]] = []

    def submit(self, tenant_id: TenantId, task_name: str, *task_args: str) -> str:
        self.submitted.append((tenant_id, task_name, task_args))
        return "job_x"


def _app(submitter: FakeSubmitter, *, enabled: bool = True) -> FastAPI:
    app = create_app(_settings(enabled=enabled))
    app.dependency_overrides[get_app_settings] = lambda: _settings(enabled=enabled)
    app.dependency_overrides[get_job_submitter] = lambda: submitter
    return app


def test_ingest_invoices_returns_202_and_enqueues_with_window_and_connector() -> None:
    submitter = FakeSubmitter()
    client = TestClient(_app(submitter))
    response = client.post(
        "/api/v1/ingestion/invoices",
        headers=AUTH,
        json={"connector_id": "con_1", "window": WINDOW_JSON},
    )
    assert response.status_code == 202
    assert response.json() == {"job_id": "job_x"}
    tenant, task_name, args = submitter.submitted[0]
    assert tenant == TenantId("tenant-1")
    assert task_name == INGEST_INVOICES_TASK
    assert args == ("2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00", "con_1")


def test_ingest_usage_events_returns_202() -> None:
    submitter = FakeSubmitter()
    client = TestClient(_app(submitter))
    response = client.post(
        "/api/v1/ingestion/usage-events",
        headers=AUTH,
        json={"connector_id": "con_1", "window": WINDOW_JSON},
    )
    assert response.status_code == 202
    assert submitter.submitted[0][1] == INGEST_USAGE_EVENTS_TASK


@pytest.mark.parametrize("path", ["invoices", "usage-events"])
def test_ingestion_is_403_when_flag_is_off(path: str) -> None:
    client = TestClient(_app(FakeSubmitter(), enabled=False))
    response = client.post(
        f"/api/v1/ingestion/{path}",
        headers=AUTH,
        json={"connector_id": "con_1", "window": WINDOW_JSON},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ingestion_disabled"


def test_ingestion_requires_bearer_auth() -> None:
    client = TestClient(_app(FakeSubmitter()))
    response = client.post(
        "/api/v1/ingestion/invoices", json={"connector_id": "con_1", "window": WINDOW_JSON}
    )
    assert response.status_code == 401


def test_job_submitter_persists_pending_job_then_commits_then_enqueues() -> None:
    events: list[str] = []

    class FakeSession:
        def commit(self) -> None:
            events.append("commit")

    class FakeJobs:
        def add(self, tenant_id: TenantId, job: Job) -> None:
            events.append("add")
            assert job.status is JobStatus.PENDING
            assert job.job_type is JobType.INGEST_INVOICES
            assert job.created_at.tzinfo is not None

    class FakeQueue:
        def enqueue(self, task_name: str, *args: str) -> str:
            events.append("enqueue")
            assert task_name == INGEST_INVOICES_TASK
            assert args[1] == "tenant-1"  # (job_id, tenant_id, *task_args)
            return "celery-task-id"

    submitter = JobSubmitter(FakeSession(), FakeJobs(), FakeQueue())  # type: ignore[arg-type]
    job_id = submitter.submit(TenantId("tenant-1"), INGEST_INVOICES_TASK, "a", "b")
    assert job_id.startswith("job_")
    # The PENDING row is durable BEFORE the broker can deliver the task (§3 race guard).
    assert events == ["add", "commit", "enqueue"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_ingestion_router.py -q`
Expected: FAIL — `ImportError` (no `INGEST_INVOICES_TASK`/`JobSubmitter` in services yet).

- [ ] **Step 3: Add the submission seam to services**

In `backend/src/yieldfield/api/v1/dependencies/services.py`, add to the imports:

```python
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from yieldfield.api.v1.dependencies.tasks import TaskQueue, TaskQueueDep
from yieldfield.domain.shared.ids import TenantId
from yieldfield.infrastructure.persistence.job import Job, JobStatus, JobType
```

(merge with the existing `Job` import from Task 4 — one import line: `from yieldfield.infrastructure.persistence.job import Job, JobStatus, JobType`), then append:

```python
# Task names are the API↔worker contract: the API enqueues by name (never imports task
# functions), the worker registers tasks under exactly these names (spec §7).
INGEST_INVOICES_TASK = "yieldfield.ingest_invoices"
INGEST_USAGE_EVENTS_TASK = "yieldfield.ingest_usage_events"
RUN_RECONCILIATION_TASK = "yieldfield.run_reconciliation"

_JOB_TYPE_BY_TASK: dict[str, JobType] = {
    INGEST_INVOICES_TASK: JobType.INGEST_INVOICES,
    INGEST_USAGE_EVENTS_TASK: JobType.INGEST_USAGE_EVENTS,
    RUN_RECONCILIATION_TASK: JobType.RUN_RECONCILIATION,
}


@dataclass(frozen=True, slots=True)
class JobSubmitter:
    """Create the PENDING Job, COMMIT it, then enqueue — in that order (§3).

    The commit-before-enqueue ordering is load-bearing: with `task_acks_late` a fast worker
    can pick the task up immediately, and `run_as_job` must find the Job row. Worker args
    convention: (job_id, tenant_id, *task_args), all strings (JSON-serializable).
    """

    session: Session
    jobs: SqlAlchemyJobRepository
    queue: TaskQueue

    def submit(self, tenant_id: TenantId, task_name: str, *task_args: str) -> str:
        job_id = f"job_{uuid4()}"
        self.jobs.add(
            tenant_id,
            Job(
                id=job_id,
                tenant_id=tenant_id,
                job_type=_JOB_TYPE_BY_TASK[task_name],
                status=JobStatus.PENDING,
                created_at=datetime.now(UTC),
            ),
        )
        self.session.commit()
        self.queue.enqueue(task_name, job_id, str(tenant_id), *task_args)
        return job_id


def get_job_submitter(session: DbSession, queue: TaskQueueDep) -> JobSubmitter:
    return JobSubmitter(session, SqlAlchemyJobRepository(session), queue)


JobSubmitterDep = Annotated[JobSubmitter, Depends(get_job_submitter)]
```

- [ ] **Step 4: Create the ingestion router and wire it**

Create `backend/src/yieldfield/api/v1/routers/ingestion.py`:

```python
"""POST /ingestion/{invoices,usage-events} → 202 (spec §5.2).

Risky live pulls sit behind `ingestion_enabled` (§16) → 403 `ingestion_disabled` when off.
Each trigger persists a PENDING Job and enqueues the matching worker task; connector
failures surface later as a FAILED Job via GET /jobs/{id}, not as an HTTP error here.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from yieldfield.api.errors.exceptions import IngestionDisabledError
from yieldfield.api.v1.dependencies.auth import CurrentTenant
from yieldfield.api.v1.dependencies.services import (
    INGEST_INVOICES_TASK,
    INGEST_USAGE_EVENTS_TASK,
    JobSubmitterDep,
)
from yieldfield.api.v1.dependencies.settings import SettingsDep
from yieldfield.api.v1.schemas.common import JobAccepted
from yieldfield.api.v1.schemas.ingestion import IngestionRequest
from yieldfield.config.settings import Settings

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


def _require_enabled(settings: Settings) -> None:
    if not settings.ingestion_enabled:
        raise IngestionDisabledError(
            "Ingestion is disabled (set YIELDFIELD_INGESTION_ENABLED to enable live pulls)."
        )


def _submit(
    submitter: JobSubmitterDep, tenant_id: CurrentTenant, task_name: str, body: IngestionRequest
) -> JobAccepted:
    job_id = submitter.submit(
        tenant_id,
        task_name,
        body.window.start.isoformat(),
        body.window.end.isoformat(),
        body.connector_id,
    )
    return JobAccepted(job_id=job_id)


@router.post(
    "/invoices",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger invoice ingestion",
    response_model=JobAccepted,
)
def ingest_invoices(
    body: IngestionRequest,
    tenant_id: CurrentTenant,
    settings: SettingsDep,
    submitter: JobSubmitterDep,
) -> JobAccepted:
    _require_enabled(settings)
    return _submit(submitter, tenant_id, INGEST_INVOICES_TASK, body)


@router.post(
    "/usage-events",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger usage-event ingestion",
    response_model=JobAccepted,
)
def ingest_usage_events(
    body: IngestionRequest,
    tenant_id: CurrentTenant,
    settings: SettingsDep,
    submitter: JobSubmitterDep,
) -> JobAccepted:
    _require_enabled(settings)
    return _submit(submitter, tenant_id, INGEST_USAGE_EVENTS_TASK, body)
```

In `backend/src/yieldfield/api/main.py`, extend the routers import to `from yieldfield.api.v1.routers import connectors, health, ingestion, jobs` and add `app.include_router(ingestion.router, prefix=API_V1_PREFIX)`.

- [ ] **Step 5: Run to verify it passes + gates**

Run:
```bash
uv run pytest tests/unit/test_ingestion_router.py -q
uv run mypy
uv run ruff check . && uv run black --check .
```
Expected: 6 passed; mypy `Success`; ruff/black clean (delete the trailing `_ = datetime...` line if ruff flags it).

- [ ] **Step 6: Commit**

```bash
git add backend/src/yieldfield/api/v1/routers/ingestion.py backend/src/yieldfield/api/v1/dependencies/services.py backend/src/yieldfield/api/main.py backend/tests/unit/test_ingestion_router.py
git commit -m "feat(api): flag-gated ingestion triggers with commit-before-enqueue jobs (§3/§5.2)"
```

---

## Task 7: Reconciliations router — `POST /reconciliations` → 202, `GET` by id + list

**Files:**
- Create: `backend/src/yieldfield/api/v1/routers/reconciliations.py`
- Modify: `backend/src/yieldfield/api/main.py` (include router)
- Test: `backend/tests/unit/test_reconciliations_router.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_reconciliations_router.py`:

```python
"""POST /reconciliations pre-generates the run id (decision C/E); GETs read the audit trail."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from yieldfield.api.main import create_app
from yieldfield.api.v1.dependencies.services import (
    RUN_RECONCILIATION_TASK,
    get_job_submitter,
    get_reconciliation_repository,
)
from yieldfield.api.v1.dependencies.settings import get_app_settings
from yieldfield.config.settings import Settings
from yieldfield.domain.reconciliation.reconciliation import Reconciliation
from yieldfield.domain.shared.ids import ReconciliationId, TenantId
from yieldfield.domain.shared.time_window import TimeWindow

AUTH = {"Authorization": "Bearer tok-1"}
WINDOW_JSON = {"start": "2026-01-01T00:00:00+00:00", "end": "2026-02-01T00:00:00+00:00"}
WINDOW = TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))


def _settings() -> Settings:
    return Settings(_env_file=None, api_tokens={"tok-1": "tenant-1"})


def _recon(recon_id: str, executed_at: datetime) -> Reconciliation:
    return Reconciliation(
        id=ReconciliationId(recon_id),
        tenant_id=TenantId("tenant-1"),
        window=WINDOW,
        currency="USD",
        executed_at=executed_at,
        rule_version="reconciliation-v1",
        findings=(),
    )


class FakeSubmitter:
    def __init__(self) -> None:
        self.submitted: list[tuple[TenantId, str, tuple[str, ...]]] = []

    def submit(self, tenant_id: TenantId, task_name: str, *task_args: str) -> str:
        self.submitted.append((tenant_id, task_name, task_args))
        return "job_x"


class FakeReconRepo:
    def __init__(self, reconciliations: Sequence[Reconciliation]) -> None:
        self._reconciliations = list(reconciliations)

    def get(
        self, tenant_id: TenantId, reconciliation_id: ReconciliationId
    ) -> Reconciliation | None:
        for r in self._reconciliations:
            if r.id == reconciliation_id:
                return r
        return None

    def list_for_tenant(self, tenant_id: TenantId) -> Sequence[Reconciliation]:
        return list(self._reconciliations)


def _app(submitter: FakeSubmitter, repo: FakeReconRepo | None = None) -> FastAPI:
    app = create_app(_settings())
    app.dependency_overrides[get_app_settings] = _settings
    app.dependency_overrides[get_job_submitter] = lambda: submitter
    app.dependency_overrides[get_reconciliation_repository] = lambda: repo or FakeReconRepo([])
    return app


def test_post_returns_202_and_pre_generates_the_reconciliation_id() -> None:
    submitter = FakeSubmitter()
    client = TestClient(_app(submitter))
    response = client.post("/api/v1/reconciliations", headers=AUTH, json={"window": WINDOW_JSON})
    assert response.status_code == 202
    assert response.json() == {"job_id": "job_x"}
    tenant, task_name, args = submitter.submitted[0]
    assert task_name == RUN_RECONCILIATION_TASK
    assert args[0] == "2026-01-01T00:00:00+00:00"
    assert args[2].startswith("rec_")  # pre-generated so worker retries converge (decision C/E)


def test_get_by_id_returns_the_financial_read() -> None:
    repo = FakeReconRepo([_recon("rec_1", datetime(2026, 3, 1, tzinfo=UTC))])
    client = TestClient(_app(FakeSubmitter(), repo))
    response = client.get("/api/v1/reconciliations/rec_1", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "rec_1"
    assert body["total_leakage"] == {"amount": "0", "currency": "USD"}
    assert body["rule_version"] == "reconciliation-v1"


def test_get_missing_is_404() -> None:
    client = TestClient(_app(FakeSubmitter()))
    response = client.get("/api/v1/reconciliations/nope", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_list_is_newest_first_and_paginated() -> None:
    repo = FakeReconRepo(
        [
            _recon("rec_old", datetime(2026, 1, 5, tzinfo=UTC)),
            _recon("rec_new", datetime(2026, 3, 5, tzinfo=UTC)),
            _recon("rec_mid", datetime(2026, 2, 5, tzinfo=UTC)),
        ]
    )
    client = TestClient(_app(FakeSubmitter(), repo))
    response = client.get("/api/v1/reconciliations?limit=2", headers=AUTH)
    body = response.json()
    assert [r["id"] for r in body["items"]] == ["rec_new", "rec_mid"]  # newest first (§5.2)
    assert body["meta"]["next_cursor"] is not None


def test_reconciliations_require_bearer_auth() -> None:
    client = TestClient(_app(FakeSubmitter()))
    assert client.post("/api/v1/reconciliations", json={"window": WINDOW_JSON}).status_code == 401
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_reconciliations_router.py -q`
Expected: FAIL — 404s (routes don't exist yet).

- [ ] **Step 3: Create the router and wire it**

Create `backend/src/yieldfield/api/v1/routers/reconciliations.py`:

```python
"""POST/GET /reconciliations (spec §5.2): trigger a run (202 + job handle) and read the
append-only financial audit trail (decision C).

The API pre-generates `reconciliation_id` and passes it with the job, so a Celery
redelivery/retry converges on the same run while a fresh POST is a new historical record
(decision C/E). Reads are newest-first; each run is immutable.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, status

from yieldfield.api.v1.dependencies.auth import CurrentTenant
from yieldfield.api.v1.dependencies.pagination import PageParamsDep, paginate
from yieldfield.api.v1.dependencies.services import (
    RUN_RECONCILIATION_TASK,
    JobSubmitterDep,
    ReconciliationRepo,
)
from yieldfield.api.v1.schemas.common import JobAccepted, PageMeta
from yieldfield.api.v1.schemas.reconciliations import (
    ReconciliationCreate,
    ReconciliationPage,
    ReconciliationRead,
)
from yieldfield.application.errors import EntityNotFoundError
from yieldfield.domain.shared.ids import ReconciliationId

router = APIRouter(prefix="/reconciliations", tags=["reconciliations"])


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run reconciliation for a window",
    response_model=JobAccepted,
)
def run_reconciliation(
    body: ReconciliationCreate, tenant_id: CurrentTenant, submitter: JobSubmitterDep
) -> JobAccepted:
    reconciliation_id = f"rec_{uuid4()}"
    job_id = submitter.submit(
        tenant_id,
        RUN_RECONCILIATION_TASK,
        body.window.start.isoformat(),
        body.window.end.isoformat(),
        reconciliation_id,
    )
    return JobAccepted(job_id=job_id)


@router.get(
    "/{reconciliation_id}",
    summary="Read one reconciliation run",
    response_model=ReconciliationRead,
)
def get_reconciliation(
    reconciliation_id: str, tenant_id: CurrentTenant, reconciliations: ReconciliationRepo
) -> ReconciliationRead:
    reconciliation = reconciliations.get(tenant_id, ReconciliationId(reconciliation_id))
    if reconciliation is None:
        raise EntityNotFoundError(f"Reconciliation {reconciliation_id!r} not found.")
    return ReconciliationRead.from_reconciliation(reconciliation)


@router.get("", summary="List reconciliation runs (newest first)", response_model=ReconciliationPage)
def list_reconciliations(
    tenant_id: CurrentTenant, reconciliations: ReconciliationRepo, page: PageParamsDep
) -> ReconciliationPage:
    ordered = sorted(
        reconciliations.list_for_tenant(tenant_id), key=lambda r: r.executed_at, reverse=True
    )
    items, next_cursor = paginate(ordered, page)
    return ReconciliationPage(
        items=[ReconciliationRead.from_reconciliation(r) for r in items],
        meta=PageMeta(next_cursor=next_cursor),
    )
```

In `backend/src/yieldfield/api/main.py`, extend the routers import to `from yieldfield.api.v1.routers import connectors, health, ingestion, jobs, reconciliations` and add `app.include_router(reconciliations.router, prefix=API_V1_PREFIX)`.

- [ ] **Step 4: Run to verify it passes + gates**

Run:
```bash
uv run pytest tests/unit/test_reconciliations_router.py -q
uv run mypy
```
Expected: 5 passed; mypy `Success`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/yieldfield/api/v1/routers/reconciliations.py backend/src/yieldfield/api/main.py backend/tests/unit/test_reconciliations_router.py
git commit -m "feat(api): reconciliation trigger + append-only audit reads (§5.2, decision C)"
```

---

## Task 8: Findings router — list/read + the four explicit transitions

**Files:**
- Create: `backend/src/yieldfield/api/v1/routers/findings.py`
- Modify: `backend/src/yieldfield/api/main.py` (include router)
- Test: `backend/tests/unit/test_findings_router.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_findings_router.py`:

```python
"""Findings reads + the four explicit lifecycle routes (decision D): one use-case behind them."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from yieldfield.api.main import create_app
from yieldfield.api.v1.dependencies.services import get_finding_repository
from yieldfield.api.v1.dependencies.settings import get_app_settings
from yieldfield.config.settings import Settings
from yieldfield.domain.findings.finding import Finding, FindingLineage
from yieldfield.domain.findings.leakage_type import LeakageType
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.findings.severity import Severity
from yieldfield.domain.shared.ids import FindingId, ReconciliationId, TenantId
from yieldfield.domain.shared.money import Money

AUTH = {"Authorization": "Bearer tok-1"}


def _settings() -> Settings:
    return Settings(_env_file=None, api_tokens={"tok-1": "tenant-1"})


def _finding(finding_id: str = "f_1", status: RecoveryStatus = RecoveryStatus.NEW) -> Finding:
    return Finding(
        id=FindingId(finding_id),
        tenant_id=TenantId("tenant-1"),
        reconciliation_id=ReconciliationId("rec_1"),
        customer_id="cus_1",
        metric="api_calls",
        leakage_type=LeakageType.UNBILLED_USAGE,
        severity=Severity.LOW,
        amount=Money.of("10.00", "USD"),
        status=status,
        lineage=FindingLineage(rule_version="reconciliation-v1"),
        explanation="100 api_calls were not billed.",
    )


class FakeFindingRepo:
    def __init__(self, findings: Sequence[Finding]) -> None:
        self._findings = {str(f.id): f for f in findings}
        self.updated: list[Finding] = []

    def get(self, tenant_id: TenantId, finding_id: FindingId) -> Finding | None:
        return self._findings.get(str(finding_id))

    def list_for_reconciliation(
        self, tenant_id: TenantId, reconciliation_id: ReconciliationId
    ) -> Sequence[Finding]:
        return [f for f in self._findings.values() if f.reconciliation_id == reconciliation_id]

    def update(self, tenant_id: TenantId, finding: Finding) -> None:
        self.updated.append(finding)
        self._findings[str(finding.id)] = finding


def _app(repo: FakeFindingRepo) -> FastAPI:
    app = create_app(_settings())
    app.dependency_overrides[get_app_settings] = _settings
    app.dependency_overrides[get_finding_repository] = lambda: repo
    return app


def test_list_findings_filters_by_reconciliation_id() -> None:
    client = TestClient(_app(FakeFindingRepo([_finding("f_1"), _finding("f_2")])))
    response = client.get("/api/v1/findings?reconciliation_id=rec_1", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert {f["id"] for f in body["items"]} == {"f_1", "f_2"}
    assert body["items"][0]["amount"] == {"amount": "10.00", "currency": "USD"}


def test_list_requires_the_reconciliation_id_filter() -> None:
    client = TestClient(_app(FakeFindingRepo([])))
    response = client.get("/api/v1/findings", headers=AUTH)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_get_finding_by_id() -> None:
    client = TestClient(_app(FakeFindingRepo([_finding()])))
    response = client.get("/api/v1/findings/f_1", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["explanation"] == "100 api_calls were not billed."


def test_get_missing_finding_is_404() -> None:
    client = TestClient(_app(FakeFindingRepo([])))
    response = client.get("/api/v1/findings/nope", headers=AUTH)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    ("action", "start", "expected"),
    [
        ("review", RecoveryStatus.NEW, "reviewed"),
        ("confirm", RecoveryStatus.REVIEWED, "confirmed"),
        ("dismiss", RecoveryStatus.NEW, "dismissed"),
        ("recover", RecoveryStatus.CONFIRMED, "recovered"),
    ],
)
def test_each_explicit_route_applies_its_transition_and_persists(
    action: str, start: RecoveryStatus, expected: str
) -> None:
    repo = FakeFindingRepo([_finding(status=start)])
    client = TestClient(_app(repo))
    response = client.post(f"/api/v1/findings/f_1/{action}", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["status"] == expected
    assert repo.updated[0].status.value == expected


def test_illegal_transition_is_409_and_not_persisted() -> None:
    repo = FakeFindingRepo([_finding(status=RecoveryStatus.NEW)])
    client = TestClient(_app(repo))
    response = client.post("/api/v1/findings/f_1/confirm", headers=AUTH)  # NEW→CONFIRMED illegal
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_finding_transition"
    assert repo.updated == []


def test_findings_require_bearer_auth() -> None:
    client = TestClient(_app(FakeFindingRepo([])))
    assert client.get("/api/v1/findings?reconciliation_id=rec_1").status_code == 401
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_findings_router.py -q`
Expected: FAIL — 404s (routes don't exist yet).

- [ ] **Step 3: Create the router and wire it**

Create `backend/src/yieldfield/api/v1/routers/findings.py`:

```python
"""Findings reads + explicit lifecycle routes (spec §5.2, decision D).

Four explicit POST routes — review/confirm/dismiss/recover — each mapping 1:1 to a domain
transition, all behind the single TransitionFinding use-case (§4.3). Illegal transitions
are 409 (`invalid_finding_transition`); the use-case guarantees nothing persists on an
illegal request.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from yieldfield.api.v1.dependencies.auth import CurrentTenant
from yieldfield.api.v1.dependencies.pagination import PageParamsDep, paginate
from yieldfield.api.v1.dependencies.services import FindingRepo
from yieldfield.api.v1.schemas.common import PageMeta
from yieldfield.api.v1.schemas.findings import FindingPage, FindingRead
from yieldfield.application.errors import EntityNotFoundError
from yieldfield.application.findings.transition_finding import TransitionFinding
from yieldfield.domain.findings.recovery_status import RecoveryStatus
from yieldfield.domain.shared.ids import FindingId, ReconciliationId, TenantId

router = APIRouter(prefix="/findings", tags=["findings"])


@router.get("", summary="List findings for a reconciliation run", response_model=FindingPage)
def list_findings(
    tenant_id: CurrentTenant,
    findings: FindingRepo,
    page: PageParamsDep,
    reconciliation_id: Annotated[str, Query()],
) -> FindingPage:
    rows = findings.list_for_reconciliation(tenant_id, ReconciliationId(reconciliation_id))
    items, next_cursor = paginate(rows, page)
    return FindingPage(
        items=[FindingRead.from_finding(f) for f in items],
        meta=PageMeta(next_cursor=next_cursor),
    )


@router.get("/{finding_id}", summary="Read one finding", response_model=FindingRead)
def get_finding(
    finding_id: str, tenant_id: CurrentTenant, findings: FindingRepo
) -> FindingRead:
    finding = findings.get(tenant_id, FindingId(finding_id))
    if finding is None:
        raise EntityNotFoundError(f"Finding {finding_id!r} not found.")
    return FindingRead.from_finding(finding)


def _transition(
    findings: FindingRepo, tenant_id: TenantId, finding_id: str, target: RecoveryStatus
) -> FindingRead:
    updated = TransitionFinding(findings).run(tenant_id, FindingId(finding_id), target)
    return FindingRead.from_finding(updated)


@router.post("/{finding_id}/review", summary="Mark reviewed", response_model=FindingRead)
def review(finding_id: str, tenant_id: CurrentTenant, findings: FindingRepo) -> FindingRead:
    return _transition(findings, tenant_id, finding_id, RecoveryStatus.REVIEWED)


@router.post("/{finding_id}/confirm", summary="Confirm leakage", response_model=FindingRead)
def confirm(finding_id: str, tenant_id: CurrentTenant, findings: FindingRepo) -> FindingRead:
    return _transition(findings, tenant_id, finding_id, RecoveryStatus.CONFIRMED)


@router.post("/{finding_id}/dismiss", summary="Dismiss finding", response_model=FindingRead)
def dismiss(finding_id: str, tenant_id: CurrentTenant, findings: FindingRepo) -> FindingRead:
    return _transition(findings, tenant_id, finding_id, RecoveryStatus.DISMISSED)


@router.post("/{finding_id}/recover", summary="Mark dollars recovered", response_model=FindingRead)
def recover(finding_id: str, tenant_id: CurrentTenant, findings: FindingRepo) -> FindingRead:
    return _transition(findings, tenant_id, finding_id, RecoveryStatus.RECOVERED)
```

In `backend/src/yieldfield/api/main.py`, extend the routers import to `from yieldfield.api.v1.routers import connectors, findings, health, ingestion, jobs, reconciliations` and add `app.include_router(findings.router, prefix=API_V1_PREFIX)`.

- [ ] **Step 4: Run to verify it passes + gates**

Run:
```bash
uv run pytest tests/unit/test_findings_router.py -q
uv run mypy
uv run lint-imports
```
Expected: 10 passed; mypy `Success`; `Contracts: 4 kept, 0 broken.`

- [ ] **Step 5: Commit**

```bash
git add backend/src/yieldfield/api/v1/routers/findings.py backend/src/yieldfield/api/main.py backend/tests/unit/test_findings_router.py
git commit -m "feat(api): findings reads + four explicit lifecycle routes (§5.2, decision D)"
```

---

## Task 9: Webhooks — `POST /api/v1/webhooks/{connector_id}`

**Files:**
- Create: `backend/src/yieldfield/api/webhooks/router.py`
- Modify: `backend/src/yieldfield/api/main.py` (include router)
- Test: `backend/tests/unit/test_webhooks_router.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_webhooks_router.py`:

```python
"""Webhooks route by connector_id; the SIGNATURE is the authentication (decision F, §11)."""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import FastAPI
from fastapi.testclient import TestClient

from yieldfield.api.main import create_app
from yieldfield.api.v1.dependencies.services import (
    INGEST_INVOICES_TASK,
    get_connector_store,
    get_job_submitter,
    get_registration_service,
)
from yieldfield.api.v1.dependencies.settings import get_app_settings
from yieldfield.config.settings import Settings
from yieldfield.domain.billing.connector import Connector, ConnectorStatus, ConnectorType
from yieldfield.domain.billing.connector_port import ConnectorCredentials
from yieldfield.domain.billing.invoice import Invoice
from yieldfield.domain.billing.usage_event import UsageEvent
from yieldfield.domain.shared.ids import ConnectorId, TenantId
from yieldfield.domain.shared.time_window import TimeWindow


def _settings() -> Settings:
    return Settings(_env_file=None)  # NOTE: no api_tokens — webhooks use no bearer auth


def _connector() -> Connector:
    return Connector(
        id=ConnectorId("con_1"),
        tenant_id=TenantId("tenant-1"),
        connector_type=ConnectorType.STRIPE_BILLING,
        status=ConnectorStatus.ACTIVE,
    )


class FakeLiveConnector:
    def __init__(self, *, valid: bool) -> None:
        self._valid = valid
        self.verified: list[tuple[bytes, str]] = []

    def authenticate(self, credentials: ConnectorCredentials) -> None:
        return None

    def pull_usage_events(self, window: TimeWindow) -> Iterable[UsageEvent]:
        return []

    def pull_invoices(self, window: TimeWindow) -> Iterable[Invoice]:
        return []

    def verify_webhook(self, payload: bytes, signature: str) -> bool:
        self.verified.append((payload, signature))
        return self._valid


class FakeStore:
    def __init__(self, connector: Connector | None) -> None:
        self._connector = connector

    def find_by_id(self, connector_id: ConnectorId) -> Connector | None:
        if self._connector is not None and self._connector.id == connector_id:
            return self._connector
        return None


class FakeRegistration:
    def __init__(self, live: FakeLiveConnector) -> None:
        self.live = live

    def build_authenticated(
        self, tenant_id: TenantId, connector_id: ConnectorId
    ) -> FakeLiveConnector:
        return self.live


class FakeSubmitter:
    def __init__(self) -> None:
        self.submitted: list[tuple[TenantId, str, tuple[str, ...]]] = []

    def submit(self, tenant_id: TenantId, task_name: str, *task_args: str) -> str:
        self.submitted.append((tenant_id, task_name, task_args))
        return "job_x"


def _app(
    store: FakeStore, registration: FakeRegistration, submitter: FakeSubmitter
) -> FastAPI:
    app = create_app(_settings())
    app.dependency_overrides[get_app_settings] = _settings
    app.dependency_overrides[get_connector_store] = lambda: store
    app.dependency_overrides[get_registration_service] = lambda: registration
    app.dependency_overrides[get_job_submitter] = lambda: submitter
    return app


def test_valid_signature_returns_202_and_enqueues_a_repull_for_the_owning_tenant() -> None:
    live = FakeLiveConnector(valid=True)
    submitter = FakeSubmitter()
    client = TestClient(_app(FakeStore(_connector()), FakeRegistration(live), submitter))
    response = client.post(
        "/api/v1/webhooks/con_1",
        content=b'{"type":"invoice.paid"}',
        headers={"Stripe-Signature": "t=1,v1=abc"},
    )
    assert response.status_code == 202
    assert response.json() == {"job_id": "job_x"}
    assert live.verified == [(b'{"type":"invoice.paid"}', "t=1,v1=abc")]
    tenant, task_name, args = submitter.submitted[0]
    assert tenant == TenantId("tenant-1")  # tenant resolved from the connector, not a token
    assert task_name == INGEST_INVOICES_TASK
    assert args[2] == "con_1"  # (start, end, connector_id)


def test_invalid_signature_is_400_and_enqueues_nothing() -> None:
    submitter = FakeSubmitter()
    client = TestClient(
        _app(FakeStore(_connector()), FakeRegistration(FakeLiveConnector(valid=False)), submitter)
    )
    response = client.post(
        "/api/v1/webhooks/con_1", content=b"{}", headers={"Stripe-Signature": "bad"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_webhook_signature"
    assert submitter.submitted == []


def test_missing_signature_header_is_400() -> None:
    client = TestClient(
        _app(
            FakeStore(_connector()),
            FakeRegistration(FakeLiveConnector(valid=False)),
            FakeSubmitter(),
        )
    )
    response = client.post("/api/v1/webhooks/con_1", content=b"{}")
    assert response.status_code == 400


def test_unknown_connector_id_is_404() -> None:
    client = TestClient(
        _app(FakeStore(None), FakeRegistration(FakeLiveConnector(valid=True)), FakeSubmitter())
    )
    response = client.post(
        "/api/v1/webhooks/nope", content=b"{}", headers={"Stripe-Signature": "t=1,v1=abc"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_webhooks_router.py -q`
Expected: FAIL — 404s (route doesn't exist yet).

- [ ] **Step 3: Create the webhook router and wire it**

Create `backend/src/yieldfield/api/webhooks/router.py`:

```python
"""POST /webhooks/{connector_id} (spec §6, decision F).

Routed by the stable connector_id: `find_by_id` resolves the owning tenant + type from the
opaque id (the single deliberate non-tenant-prescoped read — the id is the routing key and
the SIGNATURE is the authentication, §11). On a valid signature we enqueue an idempotent
re-pull of a recent window (§8 makes re-pulls safe); per-event-type payload parsing is
future work. The `Stripe-Signature` header is read directly while Stripe is the only
connector type; per-type header resolution arrives with a second connector (§17).

This package is a sanctioned composition root (§14) but still consumes the shared
dependency seam for testability. The re-pull job is NOT flag-gated at the route (a 403
would make the provider disable our endpoint); the worker task enforces the
`ingestion_enabled` gate and the Job records the outcome.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Header, Request, status

from yieldfield.api.errors.exceptions import InvalidWebhookSignatureError
from yieldfield.api.v1.dependencies.services import (
    INGEST_INVOICES_TASK,
    ConnectorStoreDep,
    JobSubmitterDep,
    RegistrationDep,
)
from yieldfield.api.v1.schemas.common import JobAccepted
from yieldfield.application.errors import EntityNotFoundError
from yieldfield.domain.shared.ids import ConnectorId

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Minimal Slice-3 behavior (spec §6): a verified event triggers a re-pull of this recent
# window rather than parsing the payload; the idempotent ingest paths make this safe (§8).
REPULL_LOOKBACK = timedelta(days=1)


@router.post(
    "/{connector_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive a signed provider webhook",
    response_model=JobAccepted,
)
async def receive_webhook(
    connector_id: str,
    request: Request,
    store: ConnectorStoreDep,
    registration: RegistrationDep,
    submitter: JobSubmitterDep,
    stripe_signature: Annotated[str, Header(alias="Stripe-Signature")] = "",
) -> JobAccepted:
    connector = store.find_by_id(ConnectorId(connector_id))
    if connector is None:
        raise EntityNotFoundError(f"Connector {connector_id!r} not found.")

    payload = await request.body()
    live = registration.build_authenticated(connector.tenant_id, connector.id)
    if not live.verify_webhook(payload, stripe_signature):
        raise InvalidWebhookSignatureError("Webhook signature verification failed.")

    end = datetime.now(UTC)
    start = end - REPULL_LOOKBACK
    job_id = submitter.submit(
        connector.tenant_id,
        INGEST_INVOICES_TASK,
        start.isoformat(),
        end.isoformat(),
        connector_id,
    )
    return JobAccepted(job_id=job_id)
```

In `backend/src/yieldfield/api/main.py`, add the import `from yieldfield.api.webhooks.router import router as webhooks_router` (after the v1 routers import) and `app.include_router(webhooks_router, prefix=API_V1_PREFIX)` after the findings line.

- [ ] **Step 4: Run to verify it passes + gates**

Run:
```bash
uv run pytest tests/unit/test_webhooks_router.py -q
uv run mypy
```
Expected: 4 passed; mypy `Success`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/yieldfield/api/webhooks/router.py backend/src/yieldfield/api/main.py backend/tests/unit/test_webhooks_router.py
git commit -m "feat(api): signature-authenticated webhooks routed by connector_id (§6, decision F)"
```

---

## Task 10: `run_as_job` lifecycle wrapper (`infrastructure/messaging/`)

**Files:**
- Create: `backend/src/yieldfield/infrastructure/messaging/run_as_job.py`
- Test: `backend/tests/unit/test_run_as_job.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_run_as_job.py`:

```python
"""run_as_job (spec §3): RUNNING commits first; SUCCEEDED commits WITH the business write;
FAILED rolls business writes back first — no phantom records, durable failures."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from yieldfield.domain.shared.ids import TenantId
from yieldfield.infrastructure.messaging.run_as_job import MessagingError, run_as_job
from yieldfield.infrastructure.persistence.job import Job, JobResultType, JobStatus, JobType

TENANT = TenantId("t_1")
FIXED_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _job(status: JobStatus = JobStatus.PENDING) -> Job:
    return Job(
        id="job_1",
        tenant_id=TENANT,
        job_type=JobType.RUN_RECONCILIATION,
        status=status,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )


class FakeLedger:
    def __init__(self, job: Job | None) -> None:
        self._job = job
        self.updates: list[Job] = []

    def get(self, tenant_id: TenantId, job_id: str) -> Job | None:
        return self._job

    def update(self, tenant_id: TenantId, job: Job) -> None:
        self.updates.append(job)


class Tx:
    def __init__(self) -> None:
        self.events: list[str] = []

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")


def test_success_with_result_pair_commits_running_then_succeeded() -> None:
    ledger, tx = FakeLedger(_job()), Tx()
    run_as_job(
        jobs=ledger,
        commit=tx.commit,
        rollback=tx.rollback,
        tenant_id=TENANT,
        job_id="job_1",
        work=lambda: (JobResultType.RECONCILIATION, "rec_1"),
        clock=lambda: FIXED_NOW,
        celery_task_id="celery-1",
    )
    running, succeeded = ledger.updates
    assert running.status is JobStatus.RUNNING
    assert running.started_at == FIXED_NOW
    assert running.celery_task_id == "celery-1"
    assert succeeded.status is JobStatus.SUCCEEDED
    assert succeeded.finished_at == FIXED_NOW
    assert succeeded.result_type is JobResultType.RECONCILIATION
    assert succeeded.result_ref == "rec_1"
    assert tx.events == ["commit", "commit"]  # RUNNING txn, then business+SUCCEEDED txn


def test_success_with_no_result_leaves_the_pair_null() -> None:
    ledger, tx = FakeLedger(_job()), Tx()
    run_as_job(
        jobs=ledger,
        commit=tx.commit,
        rollback=tx.rollback,
        tenant_id=TENANT,
        job_id="job_1",
        work=lambda: None,
        clock=lambda: FIXED_NOW,
    )
    assert ledger.updates[-1].status is JobStatus.SUCCEEDED
    assert ledger.updates[-1].result_type is None
    assert ledger.updates[-1].result_ref is None


def test_failure_rolls_back_business_writes_then_records_failed_and_reraises() -> None:
    ledger, tx = FakeLedger(_job()), Tx()

    def explode() -> None:
        raise RuntimeError("connector timed out")

    with pytest.raises(RuntimeError, match="connector timed out"):
        run_as_job(
            jobs=ledger,
            commit=tx.commit,
            rollback=tx.rollback,
            tenant_id=TENANT,
            job_id="job_1",
            work=explode,
            clock=lambda: FIXED_NOW,
        )
    failed = ledger.updates[-1]
    assert failed.status is JobStatus.FAILED
    assert failed.error == "connector timed out"
    assert failed.finished_at == FIXED_NOW
    assert failed.result_type is None  # no phantom result on failure (§3)
    # Business writes are discarded BEFORE the FAILED status is committed.
    assert tx.events == ["commit", "rollback", "commit"]


def test_missing_job_raises_messaging_error() -> None:
    with pytest.raises(MessagingError, match="job_1"):
        run_as_job(
            jobs=FakeLedger(None),
            commit=lambda: None,
            rollback=lambda: None,
            tenant_id=TENANT,
            job_id="job_1",
            work=lambda: None,
        )


@pytest.mark.parametrize("status", [JobStatus.SUCCEEDED, JobStatus.FAILED])
def test_redelivery_of_a_finished_job_is_a_noop(status: JobStatus) -> None:
    # acks_late redelivery converges: a terminal job is never re-run (§3/§8).
    ledger, tx = FakeLedger(_job(status)), Tx()
    calls: list[str] = []
    run_as_job(
        jobs=ledger,
        commit=tx.commit,
        rollback=tx.rollback,
        tenant_id=TENANT,
        job_id="job_1",
        work=lambda: calls.append("ran"),  # type: ignore[func-returns-value]
    )
    assert calls == []
    assert ledger.updates == []
    assert tx.events == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_run_as_job.py -q`
Expected: FAIL — `ModuleNotFoundError: yieldfield.infrastructure.messaging.run_as_job`.

- [ ] **Step 3: Create the wrapper**

Create `backend/src/yieldfield/infrastructure/messaging/run_as_job.py`:

```python
"""Job-lifecycle wrapper for worker tasks (spec §3, §7) — the operational audit boundary.

Transaction choreography (the load-bearing part):
  txn 1: mark RUNNING (+ started_at, celery_task_id) and COMMIT — pollers see progress.
  txn 2: run `work()`; on success, mark SUCCEEDED (+ result pair) and COMMIT — the business
         write and the success status land atomically.
  on exception: ROLLBACK txn 2 (discarding any partial business writes), then mark FAILED
         (+ error, finished_at) in its own committed txn, and RE-RAISE.
A failed run therefore leaves a durable FAILED Job and no phantom financial record; a
redelivered finished job is a no-op (idempotent convergence, §8). Use-cases stay
job-unaware — only this wrapper and the worker tasks know Jobs exist.

Structured logs at the job boundary (§11): tenant_id/job_id/outcome — never secrets.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol

from yieldfield.config.logging import get_logger
from yieldfield.domain.shared.ids import TenantId
from yieldfield.infrastructure.persistence.job import Job, JobResultType, JobStatus

JobResult = tuple[JobResultType, str]

_TERMINAL = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED})


class MessagingError(Exception):
    """A job-orchestration failure (e.g. the Job row is missing)."""


class JobLedger(Protocol):
    """The slice of the job repository this wrapper needs (satisfied by SqlAlchemyJobRepository)."""

    def get(self, tenant_id: TenantId, job_id: str) -> Job | None: ...
    def update(self, tenant_id: TenantId, job: Job) -> None: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


def run_as_job(
    *,
    jobs: JobLedger,
    commit: Callable[[], None],
    rollback: Callable[[], None],
    tenant_id: TenantId,
    job_id: str,
    work: Callable[[], JobResult | None],
    clock: Callable[[], datetime] = _utcnow,
    celery_task_id: str | None = None,
) -> None:
    log = get_logger("yieldfield.jobs").bind(tenant_id=str(tenant_id), job_id=job_id)
    job = jobs.get(tenant_id, job_id)
    if job is None:
        raise MessagingError(f"Job {job_id!r} not found for tenant {tenant_id!r}.")
    if job.status in _TERMINAL:
        log.info("job.redelivered_noop", status=job.status.value)
        return

    running = replace(
        job, status=JobStatus.RUNNING, started_at=clock(), celery_task_id=celery_task_id
    )
    jobs.update(tenant_id, running)
    commit()
    log.info("job.started", job_type=job.job_type.value)

    try:
        result = work()
    except Exception as exc:
        rollback()
        failed = replace(running, status=JobStatus.FAILED, finished_at=clock(), error=str(exc))
        jobs.update(tenant_id, failed)
        commit()
        log.error("job.failed", error=str(exc))
        raise

    result_type, result_ref = result if result is not None else (None, None)
    succeeded = replace(
        running,
        status=JobStatus.SUCCEEDED,
        finished_at=clock(),
        result_type=result_type,
        result_ref=result_ref,
    )
    jobs.update(tenant_id, succeeded)
    commit()
    log.info(
        "job.succeeded",
        result_type=result_type.value if result_type is not None else None,
        result_ref=result_ref,
    )
```

- [ ] **Step 4: Run to verify it passes + types**

Run:
```bash
uv run pytest tests/unit/test_run_as_job.py -q
uv run mypy
```
Expected: 6 passed; mypy `Success`.

- [ ] **Step 5: Commit**

```bash
git add backend/src/yieldfield/infrastructure/messaging/run_as_job.py backend/tests/unit/test_run_as_job.py
git commit -m "feat(messaging): run_as_job lifecycle wrapper - durable failures, atomic success (§3)"
```

---

## Task 11: Celery worker tasks (`workers/tasks.py`)

**Files:**
- Create: `backend/src/yieldfield/workers/tasks.py`
- Test: `backend/tests/unit/test_worker_tasks.py`

Each task is its own composition root (spec §7): builds a Session (and ClickHouse client /
authenticated connector as needed), wraps the 3B use-case in `run_as_job`, owns its
transaction. Tested at unit level for the API↔worker name contract; behavior is covered by
the run_as_job unit tests (Task 10) and the E2E (Task 14, `task_always_eager`).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_worker_tasks.py`:

```python
"""The worker registers tasks under exactly the names the API enqueues (spec §7)."""

from __future__ import annotations


def test_money_path_tasks_are_registered_under_the_api_contract_names() -> None:
    import yieldfield.workers.tasks  # noqa: F401 — importing registers the tasks

    from yieldfield.api.v1.dependencies.services import (
        INGEST_INVOICES_TASK,
        INGEST_USAGE_EVENTS_TASK,
        RUN_RECONCILIATION_TASK,
    )
    from yieldfield.workers.celery_app import celery_app

    registered = set(celery_app.tasks)
    assert {INGEST_INVOICES_TASK, INGEST_USAGE_EVENTS_TASK, RUN_RECONCILIATION_TASK} <= registered
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_worker_tasks.py -q`
Expected: FAIL — `ModuleNotFoundError: yieldfield.workers.tasks`.

- [ ] **Step 3: Create the tasks**

Create `backend/src/yieldfield/workers/tasks.py`:

```python
"""Celery tasks for the money path (spec §7) — one composition root per task.

Args are plain strings (job_id, tenant_id, *task_args) so payloads stay JSON-serializable;
windows travel as ISO-8601 with offsets. The engine and ClickHouse client are built once
per worker process (lru_cache); each task run owns one Session and its transactions via
`run_as_job`. Ingestion tasks re-check the `ingestion_enabled` flag (defense in depth
behind the API gate, §16): when off they fail the Job rather than silently pulling.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from yieldfield.application.ingestion.ingest_invoices import IngestInvoices
from yieldfield.application.ingestion.ingest_usage_events import IngestUsageEvents
from yieldfield.application.reconciliation.run_reconciliation import RunReconciliation
from yieldfield.config.logging import get_logger
from yieldfield.config.settings import get_settings
from yieldfield.domain.shared.ids import ConnectorId, ReconciliationId, TenantId
from yieldfield.domain.shared.time_window import TimeWindow
from yieldfield.infrastructure.analytics_store.clickhouse_client import create_clickhouse_client
from yieldfield.infrastructure.analytics_store.clickhouse_usage_event_store import (
    ClickHouseUsageEventStore,
)
from yieldfield.infrastructure.connectors.registration import ConnectorRegistrationService
from yieldfield.infrastructure.messaging.run_as_job import JobResult, run_as_job
from yieldfield.infrastructure.persistence.engine import build_sessionmaker, create_db_engine
from yieldfield.infrastructure.persistence.job import JobResultType
from yieldfield.infrastructure.persistence.repositories import (
    SqlAlchemyConnectorRepository,
    SqlAlchemyContractRepository,
    SqlAlchemyInvoiceRepository,
    SqlAlchemyJobRepository,
    SqlAlchemyPlanRepository,
    SqlAlchemyReconciliationRepository,
)
from yieldfield.infrastructure.security.credential_cipher import (
    CredentialCipherError,
    FernetCredentialCipher,
)
from yieldfield.workers.celery_app import celery_app

_log = get_logger("yieldfield.workers")


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    return build_sessionmaker(create_db_engine(get_settings().database_url))


@lru_cache(maxsize=1)
def _usage_event_store() -> ClickHouseUsageEventStore:
    return ClickHouseUsageEventStore(create_clickhouse_client(get_settings().clickhouse_url))


def _window(start: str, end: str) -> TimeWindow:
    return TimeWindow(datetime.fromisoformat(start), datetime.fromisoformat(end))


def _registration(session: Session) -> ConnectorRegistrationService:
    settings = get_settings()
    if not settings.credentials_key:
        raise CredentialCipherError(
            "YIELDFIELD_CREDENTIALS_KEY is required to use connectors (§16)."
        )
    return ConnectorRegistrationService(
        SqlAlchemyConnectorRepository(session),
        FernetCredentialCipher(settings.credentials_key),
        base_url=settings.connector_base_url,
    )


def _require_ingestion_enabled() -> None:
    if not get_settings().ingestion_enabled:
        raise RuntimeError("Ingestion is disabled (YIELDFIELD_INGESTION_ENABLED).")


@celery_app.task(name="yieldfield.run_reconciliation", bind=True)  # type: ignore[untyped-decorator]  # Celery decorator is untyped
def run_reconciliation_task(
    self: Any, job_id: str, tenant_id: str, start: str, end: str, reconciliation_id: str
) -> None:
    tenant = TenantId(tenant_id)
    with _session_factory()() as session:

        def work() -> JobResult:
            use_case = RunReconciliation(
                SqlAlchemyInvoiceRepository(session),
                _usage_event_store(),
                SqlAlchemyContractRepository(session),
                SqlAlchemyPlanRepository(session),
                SqlAlchemyReconciliationRepository(session),
            )
            reconciliation = use_case.run(
                tenant, _window(start, end), ReconciliationId(reconciliation_id)
            )
            _log.info(
                "reconciliation.completed",
                tenant_id=tenant_id,
                job_id=job_id,
                reconciliation_id=reconciliation_id,
                finding_count=reconciliation.finding_count,
            )
            return (JobResultType.RECONCILIATION, str(reconciliation.id))

        run_as_job(
            jobs=SqlAlchemyJobRepository(session),
            commit=session.commit,
            rollback=session.rollback,
            tenant_id=tenant,
            job_id=job_id,
            work=work,
            celery_task_id=self.request.id,
        )


@celery_app.task(name="yieldfield.ingest_invoices", bind=True)  # type: ignore[untyped-decorator]  # Celery decorator is untyped
def ingest_invoices_task(
    self: Any, job_id: str, tenant_id: str, start: str, end: str, connector_id: str
) -> None:
    tenant = TenantId(tenant_id)
    with _session_factory()() as session:

        def work() -> None:
            _require_ingestion_enabled()
            connector = _registration(session).build_authenticated(
                tenant, ConnectorId(connector_id)
            )
            count = IngestInvoices(SqlAlchemyInvoiceRepository(session)).run(
                tenant, _window(start, end), connector
            )
            _log.info(
                "ingestion.invoices_completed",
                tenant_id=tenant_id,
                job_id=job_id,
                connector_id=connector_id,
                count=count,
            )

        run_as_job(
            jobs=SqlAlchemyJobRepository(session),
            commit=session.commit,
            rollback=session.rollback,
            tenant_id=tenant,
            job_id=job_id,
            work=work,
            celery_task_id=self.request.id,
        )


@celery_app.task(name="yieldfield.ingest_usage_events", bind=True)  # type: ignore[untyped-decorator]  # Celery decorator is untyped
def ingest_usage_events_task(
    self: Any, job_id: str, tenant_id: str, start: str, end: str, connector_id: str
) -> None:
    tenant = TenantId(tenant_id)
    with _session_factory()() as session:

        def work() -> None:
            _require_ingestion_enabled()
            connector = _registration(session).build_authenticated(
                tenant, ConnectorId(connector_id)
            )
            count = IngestUsageEvents(_usage_event_store()).run(
                tenant, _window(start, end), connector
            )
            _log.info(
                "ingestion.usage_events_completed",
                tenant_id=tenant_id,
                job_id=job_id,
                connector_id=connector_id,
                count=count,
            )

        run_as_job(
            jobs=SqlAlchemyJobRepository(session),
            commit=session.commit,
            rollback=session.rollback,
            tenant_id=tenant,
            job_id=job_id,
            work=work,
            celery_task_id=self.request.id,
        )
```

Pre-flight note: verify the repository class names (`SqlAlchemyContractRepository`, `SqlAlchemyPlanRepository`, `SqlAlchemyInvoiceRepository`, `SqlAlchemyReconciliationRepository`) against `infrastructure/persistence/repositories.py` — all exist from Slice 2/3A; adapt only if a real name differs.

- [ ] **Step 4: Run to verify it passes + gates**

Run:
```bash
uv run pytest tests/unit/test_worker_tasks.py -q
uv run mypy
uv run lint-imports
```
Expected: 1 passed; mypy `Success`; `Contracts: 4 kept, 0 broken.`

- [ ] **Step 5: Commit**

```bash
git add backend/src/yieldfield/workers/tasks.py backend/tests/unit/test_worker_tasks.py
git commit -m "feat(workers): reconciliation + ingestion tasks as run_as_job composition roots (§7)"
```

---

## Task 12: `/ready` checks Postgres / ClickHouse / Redis (§11)

**Files:**
- Create: `backend/src/yieldfield/api/v1/dependencies/readiness.py`
- Modify: `backend/src/yieldfield/api/v1/routers/health.py`
- Test: `backend/tests/unit/test_readiness.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_readiness.py`:

```python
"""/ready reports per-dependency connectivity; any failure degrades to 503 (§11, §13)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from yieldfield.api.main import create_app
from yieldfield.api.v1.dependencies import readiness
from yieldfield.api.v1.dependencies.settings import get_app_settings
from yieldfield.config.settings import Settings


def _client() -> TestClient:
    # Override the settings dependency so the test never sees a developer's .env values
    # (deterministic database_url/clickhouse_url = None → "skipped").
    settings = Settings(_env_file=None)
    app = create_app(settings)
    app.dependency_overrides[get_app_settings] = lambda: settings
    return TestClient(app, raise_server_exceptions=False)


def test_ready_is_200_when_all_checks_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readiness, "_check_postgres", lambda settings: "ok")
    monkeypatch.setattr(readiness, "_check_clickhouse", lambda settings: "ok")
    monkeypatch.setattr(readiness, "_check_redis", lambda settings: "ok")
    response = _client().get("/api/v1/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"postgres": "ok", "clickhouse": "ok", "redis": "ok"}


def test_ready_degrades_to_503_when_any_check_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readiness, "_check_postgres", lambda settings: "ok")
    monkeypatch.setattr(readiness, "_check_clickhouse", lambda settings: "error")
    monkeypatch.setattr(readiness, "_check_redis", lambda settings: "ok")
    response = _client().get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["clickhouse"] == "error"


def test_unconfigured_dependencies_are_skipped_not_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # database_url/clickhouse_url default to None locally — that's "skipped", not an error.
    monkeypatch.setattr(readiness, "_check_redis", lambda settings: "ok")
    response = _client().get("/api/v1/ready")
    assert response.status_code == 200
    assert response.json()["checks"]["postgres"] == "skipped"
    assert response.json()["checks"]["clickhouse"] == "skipped"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_readiness.py -q`
Expected: FAIL — `ModuleNotFoundError: yieldfield.api.v1.dependencies.readiness`.

- [ ] **Step 3: Create the readiness checks and extend the router**

Create `backend/src/yieldfield/api/v1/dependencies/readiness.py`:

```python
"""Dependency-connectivity probes for /ready (§11, §13).

Probes REPORT, they never raise: each check returns "ok" / "error" / "skipped"
(unconfigured). Lives in dependencies/ — the API's composition seam — because the checks
build infrastructure clients (engine, ClickHouse, Redis).
"""

from __future__ import annotations

from sqlalchemy import text

from yieldfield.config.settings import Settings
from yieldfield.infrastructure.analytics_store.clickhouse_client import create_clickhouse_client
from yieldfield.infrastructure.persistence.engine import create_db_engine

_OK = "ok"
_ERROR = "error"
_SKIPPED = "skipped"


def _check_postgres(settings: Settings) -> str:
    if not settings.database_url:
        return _SKIPPED
    try:
        engine = create_db_engine(settings.database_url)
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        finally:
            engine.dispose()
        return _OK
    except Exception:
        return _ERROR


def _check_clickhouse(settings: Settings) -> str:
    if not settings.clickhouse_url:
        return _SKIPPED
    try:
        create_clickhouse_client(settings.clickhouse_url).command("SELECT 1")
        return _OK
    except Exception:
        return _ERROR


def _check_redis(settings: Settings) -> str:
    if not settings.redis_url:
        return _SKIPPED
    try:
        import redis

        redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2).ping()
        return _OK
    except Exception:
        return _ERROR


def dependency_checks(settings: Settings) -> dict[str, str]:
    return {
        "postgres": _check_postgres(settings),
        "clickhouse": _check_clickhouse(settings),
        "redis": _check_redis(settings),
    }
```

In `backend/src/yieldfield/api/v1/routers/health.py`, replace the `ready` endpoint (and extend the imports/model) so the file becomes:

```python
"""Health/readiness endpoints (§10, §11).

Liveness needs no I/O. Readiness probes the configured datastores/broker via
`dependencies/readiness.py` and degrades to 503 when any configured dependency fails —
orchestration probes get a truthful answer, and the checks themselves never raise.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from yieldfield.api.v1.dependencies import readiness
from yieldfield.api.v1.dependencies.settings import SettingsDep
from yieldfield.config.settings import get_settings

router = APIRouter(tags=["health"])


class HealthStatus(BaseModel):
    """Shallow liveness payload."""

    status: str
    service: str
    environment: str


class ReadyStatus(BaseModel):
    """Readiness payload: overall status + per-dependency connectivity (§11)."""

    status: str
    service: str
    environment: str
    checks: dict[str, str]


@router.get("/health", summary="Liveness probe")
def health() -> HealthStatus:
    settings = get_settings()
    return HealthStatus(
        status="ok",
        service=settings.app_name,
        environment=settings.environment,
    )


@router.get("/ready", summary="Readiness probe", response_model=ReadyStatus)
def ready(response: Response, settings: SettingsDep) -> ReadyStatus:
    checks = readiness.dependency_checks(settings)
    degraded = "error" in checks.values()
    if degraded:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyStatus(
        status="degraded" if degraded else "ready",
        service=settings.app_name,
        environment=settings.environment,
        checks=checks,
    )
```

- [ ] **Step 4: Run to verify it passes + gates**

Run:
```bash
uv run pytest tests/unit/test_readiness.py tests/unit/test_app_health.py -q
uv run mypy
uv run ruff check . && uv run black --check .
```
Expected: 5 passed; mypy `Success`; ruff/black clean.

- [ ] **Step 5: Commit**

```bash
git add backend/src/yieldfield/api/v1/dependencies/readiness.py backend/src/yieldfield/api/v1/routers/health.py backend/tests/unit/test_readiness.py
git commit -m "feat(api): /ready probes Postgres/ClickHouse/Redis, 503 on failure (§11)"
```

---

## Task 13: OpenAPI emission + CI drift guard (§10)

**Files:**
- Create: `ops/scripts/export_openapi.py`
- Create (generated): `contracts/openapi/openapi.json`
- Modify: `.github/workflows/ci.yml` (the `contract` job)
- Test: `backend/tests/unit/test_openapi_contract.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_openapi_contract.py`:

```python
"""The OpenAPI schema documents the full v1 surface and the committed copy never drifts (§10)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from yieldfield.api.main import create_app
from yieldfield.config.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMITTED_SCHEMA = REPO_ROOT / "contracts" / "openapi" / "openapi.json"


def test_openapi_documents_the_v1_surface() -> None:
    client = TestClient(create_app(Settings(_env_file=None)))
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    paths = set(response.json()["paths"])
    expected = {
        "/api/v1/health",
        "/api/v1/ready",
        "/api/v1/connectors",
        "/api/v1/ingestion/invoices",
        "/api/v1/ingestion/usage-events",
        "/api/v1/reconciliations",
        "/api/v1/reconciliations/{reconciliation_id}",
        "/api/v1/findings",
        "/api/v1/findings/{finding_id}",
        "/api/v1/findings/{finding_id}/review",
        "/api/v1/findings/{finding_id}/confirm",
        "/api/v1/findings/{finding_id}/dismiss",
        "/api/v1/findings/{finding_id}/recover",
        "/api/v1/jobs/{job_id}",
        "/api/v1/webhooks/{connector_id}",
    }
    assert expected <= paths


def test_committed_schema_matches_the_app() -> None:
    # The drift guard's core assertion, runnable locally (CI runs the exporter --check).
    assert COMMITTED_SCHEMA.exists(), "run: uv run python ../ops/scripts/export_openapi.py"
    committed = json.loads(COMMITTED_SCHEMA.read_text(encoding="utf-8"))
    app = create_app(Settings(_env_file=None))
    assert committed == app.openapi()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_openapi_contract.py -q`
Expected: `test_committed_schema_matches_the_app` FAILS (no committed schema yet); the surface test passes.

- [ ] **Step 3: Create the exporter**

Create `ops/scripts/export_openapi.py`:

```python
"""Emit the canonical OpenAPI schema to contracts/openapi/openapi.json (§10).

The committed schema is the shared API contract: the Slice-4 typed client generates from
it, and CI fails when the app's schema drifts from the committed copy.

Run from backend/ (the uv project):
    uv run python ../ops/scripts/export_openapi.py          # regenerate the committed file
    uv run python ../ops/scripts/export_openapi.py --check  # CI drift guard (exit 1 on drift)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = REPO_ROOT / "contracts" / "openapi" / "openapi.json"


def build_schema() -> str:
    from yieldfield.api.main import create_app
    from yieldfield.config.settings import Settings

    # Explicit default settings (no .env) so the emitted contract is environment-independent.
    app = create_app(Settings(_env_file=None))
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the OpenAPI contract (§10).")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail (exit 1) if the committed schema differs from the app's schema",
    )
    args = parser.parse_args()
    schema = build_schema()
    if args.check:
        committed = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if committed != schema:
            print(
                f"OpenAPI drift: {OUTPUT} is stale. Regenerate with: "
                "uv run python ../ops/scripts/export_openapi.py",
                file=sys.stderr,
            )
            return 1
        print("OpenAPI contract is up to date.")
        return 0
    OUTPUT.write_text(schema, encoding="utf-8")
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Generate and verify**

Run from `backend/`:
```bash
uv run python ../ops/scripts/export_openapi.py
uv run python ../ops/scripts/export_openapi.py --check
uv run pytest tests/unit/test_openapi_contract.py -q
```
Expected: `Wrote ...openapi.json`; `OpenAPI contract is up to date.`; 2 passed.

- [ ] **Step 5: Activate the CI drift guard**

In `.github/workflows/ci.yml`, replace the entire `contract` job (currently an `echo` placeholder) with:

```yaml
  contract:
    name: contract (OpenAPI drift)
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

      - name: "OpenAPI contract check (drift fails the build, §10)"
        run: uv run python ../ops/scripts/export_openapi.py --check
```

- [ ] **Step 6: Commit**

```bash
git add ops/scripts/export_openapi.py contracts/openapi/openapi.json .github/workflows/ci.yml backend/tests/unit/test_openapi_contract.py
git commit -m "feat(contracts): emit OpenAPI schema + CI drift guard (§10)"
```

---

## Task 14: E2E money path (Docker, `integration`-marked)

**Files:**
- Create: `backend/tests/e2e/conftest.py`
- Create: `backend/tests/e2e/test_money_path.py`

Two phases, both through the API with real Postgres/ClickHouse/stripe-mock containers and
the REAL worker composition roots executing inline (`task_always_eager`):
1. **Live-connector flow** (stripe-mock): register → trigger ingestion → Job SUCCEEDED.
2. **Deterministic money path:** seeded plan/contract/invoice/usage → reconcile → audit
   records + dollar totals + finding lifecycle → illegal transition 409.

Seeding uses the 3A stores directly where no API exists yet (plans/contracts routers are
Slice 4, spec §0) — and stripe-mock's canned data can't drive deterministic dollar
assertions (it also doesn't implement the Billing meter-event-summaries surface the usage
pull reads). Every API surface 3C builds is exercised end-to-end.

- [ ] **Step 1: Create the E2E fixtures**

Create `backend/tests/e2e/conftest.py`:

```python
"""E2E fixtures (spec §12): real containers + eager Celery so worker code runs inline.

Settings are injected via env vars; every process-level cache (settings, the API session
factory, the worker engine/store) is cleared around each test so each test sees this
wiring and later suites see none of it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_INI = REPO_ROOT / "ops" / "migrations" / "alembic.ini"

TENANT_ID = "tenant-e2e"
TOKEN = "e2e-token"  # noqa: S105 — test-only bearer token, not a real credential


@pytest.fixture(scope="session")
def _postgres() -> Iterator[Any]:
    try:
        from testcontainers.postgres import PostgresContainer

        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:
        pytest.skip(f"Docker/testcontainers unavailable: {exc}")
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def _clickhouse() -> Iterator[Any]:
    try:
        from testcontainers.clickhouse import ClickHouseContainer

        container = ClickHouseContainer("clickhouse/clickhouse-server:24.3-alpine")
        container.start()
    except Exception as exc:
        pytest.skip(f"Docker/testcontainers unavailable: {exc}")
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def _stripe_mock() -> Iterator[str]:
    try:
        from testcontainers.core.container import DockerContainer
        from testcontainers.core.waiting_utils import wait_for_logs

        container = DockerContainer("stripe/stripe-mock:latest").with_exposed_ports(12111)
        container.start()
        wait_for_logs(container, "Listening", timeout=30)
    except Exception as exc:
        pytest.skip(f"Docker/testcontainers unavailable: {exc}")
    try:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(12111)
        yield f"http://{host}:{port}"
    finally:
        container.stop()


@pytest.fixture(scope="session")
def _database_url(_postgres: Any) -> str:
    """Migrated-to-head database with the E2E tenant row seeded (FK target, §11)."""
    from alembic import command
    from alembic.config import Config

    from yieldfield.domain.billing.tenant import Tenant
    from yieldfield.domain.shared.ids import TenantId
    from yieldfield.infrastructure.persistence.engine import create_db_engine
    from yieldfield.infrastructure.persistence.repositories import SqlAlchemyTenantRepository

    url: str = _postgres.get_connection_url()
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    engine = create_db_engine(url)
    with Session(engine) as session:
        SqlAlchemyTenantRepository(session).add(Tenant(id=TenantId(TENANT_ID), name="E2E"))
        session.commit()
    engine.dispose()
    return url


@pytest.fixture(scope="session")
def _clickhouse_url(_clickhouse: Any) -> str:
    """ClickHouse URL with the usage_events schema provisioned."""
    from yieldfield.infrastructure.analytics_store.clickhouse_client import (
        create_clickhouse_client,
    )
    from yieldfield.infrastructure.analytics_store.clickhouse_usage_event_store import (
        ClickHouseUsageEventStore,
    )

    host = _clickhouse.get_container_host_ip()
    port = _clickhouse.get_exposed_port(8123)
    url = f"http://{_clickhouse.username}:{_clickhouse.password}@{host}:{port}/{_clickhouse.dbname}"
    ClickHouseUsageEventStore(create_clickhouse_client(url)).ensure_schema()
    return url


def _clear_process_caches() -> None:
    from yieldfield.api.v1.dependencies import database
    from yieldfield.config.settings import get_settings
    from yieldfield.workers import tasks as worker_tasks

    get_settings.cache_clear()
    database._session_factory.cache_clear()
    worker_tasks._session_factory.cache_clear()
    worker_tasks._usage_event_store.cache_clear()


@pytest.fixture()
def client(
    _database_url: str,
    _clickhouse_url: str,
    _stripe_mock: str,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setenv("YIELDFIELD_DATABASE_URL", _database_url)
    monkeypatch.setenv("YIELDFIELD_CLICKHOUSE_URL", _clickhouse_url)
    monkeypatch.setenv("YIELDFIELD_CONNECTOR_BASE_URL", _stripe_mock)
    monkeypatch.setenv("YIELDFIELD_CREDENTIALS_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("YIELDFIELD_API_TOKENS", json.dumps({TOKEN: TENANT_ID}))
    monkeypatch.setenv("YIELDFIELD_INGESTION_ENABLED", "true")
    _clear_process_caches()

    import yieldfield.workers.tasks  # noqa: F401 — registers the tasks on the celery app

    from yieldfield.api.main import create_app
    from yieldfield.workers.celery_app import celery_app

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    try:
        yield TestClient(create_app())
    finally:
        celery_app.conf.task_always_eager = False
        celery_app.conf.task_eager_propagates = False
        _clear_process_caches()
```

- [ ] **Step 2: Write the E2E tests**

Create `backend/tests/e2e/test_money_path.py`:

```python
"""The Slice-3 walking skeleton end to end (spec §12 E2E). Requires Docker."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration

# Keep in sync with conftest.py (fixtures load automatically; constants don't import
# portably across test packages without a tests/ root package).
TENANT_ID = "tenant-e2e"
AUTH = {"Authorization": "Bearer e2e-token"}

JAN_JSON = {"start": "2026-01-01T00:00:00+00:00", "end": "2026-02-01T00:00:00+00:00"}


def test_connector_registration_and_live_ingestion_against_stripe_mock(
    client: TestClient,
) -> None:
    # Register: validate (authenticate) → encrypt → persist; secrets never echo (§11).
    created = client.post(
        "/api/v1/connectors",
        headers=AUTH,
        json={
            "connector_type": "stripe_billing",
            "secrets": {"api_key": "sk_test_e2e", "webhook_secret": "whsec_e2e"},
        },
    )
    assert created.status_code == 201, created.text
    connector_id = created.json()["id"]
    assert "sk_test_e2e" not in created.text

    listed = client.get("/api/v1/connectors", headers=AUTH)
    assert connector_id in [c["id"] for c in listed.json()["items"]]

    # Live pull from stripe-mock through the REAL worker composition root (eager Celery).
    accepted = client.post(
        "/api/v1/ingestion/invoices",
        headers=AUTH,
        json={
            "connector_id": connector_id,
            # Wide window: stripe-mock's canned invoices carry fixed historic timestamps.
            "window": {"start": "2008-01-01T00:00:00+00:00", "end": "2030-01-01T00:00:00+00:00"},
        },
    )
    assert accepted.status_code == 202, accepted.text
    job = client.get(f"/api/v1/jobs/{accepted.json()['job_id']}", headers=AUTH).json()
    assert job["status"] == "succeeded", job
    assert job["result_type"] is None and job["result_ref"] is None  # ingestion: no artifact


def test_reconciliation_money_path_audit_records_and_finding_lifecycle(
    client: TestClient, _database_url: str, _clickhouse_url: str
) -> None:
    # ── Seed deterministic billing data through the 3A stores (no API for these yet, §0) ──
    from yieldfield.domain.billing.contract import Contract
    from yieldfield.domain.billing.invoice import Invoice
    from yieldfield.domain.billing.plan import Plan
    from yieldfield.domain.billing.usage_event import UsageEvent
    from yieldfield.domain.shared.ids import (
        ContractId,
        InvoiceId,
        PlanId,
        TenantId,
        UsageEventId,
    )
    from yieldfield.domain.shared.money import Money
    from yieldfield.domain.shared.time_window import TimeWindow
    from yieldfield.infrastructure.analytics_store.clickhouse_client import (
        create_clickhouse_client,
    )
    from yieldfield.infrastructure.analytics_store.clickhouse_usage_event_store import (
        ClickHouseUsageEventStore,
    )
    from yieldfield.infrastructure.persistence.engine import create_db_engine
    from yieldfield.infrastructure.persistence.repositories import (
        SqlAlchemyContractRepository,
        SqlAlchemyInvoiceRepository,
        SqlAlchemyPlanRepository,
    )

    tenant = TenantId(TENANT_ID)
    jan = TimeWindow(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))
    engine = create_db_engine(_database_url)
    with Session(engine) as session:
        SqlAlchemyPlanRepository(session).add(
            tenant,
            Plan(
                id=PlanId("p_e2e"),
                tenant_id=tenant,
                name="Metered",
                metric="api_calls",
                unit_price=Money.of("0.10", "USD"),
            ),
        )
        SqlAlchemyContractRepository(session).add(
            tenant,
            Contract(
                id=ContractId("con_e2e"),
                tenant_id=tenant,
                customer_id="cus_e2e",
                plan_id=PlanId("p_e2e"),
                term=jan,
            ),
        )
        SqlAlchemyInvoiceRepository(session).add(
            tenant,
            Invoice(
                id=InvoiceId("inv_e2e"),
                tenant_id=tenant,
                customer_id="cus_e2e",
                period=jan,
                currency="USD",
                line_items=(),  # nothing billed → 100 × $0.10 unbilled = $10.00
            ),
        )
        session.commit()
    engine.dispose()

    ClickHouseUsageEventStore(create_clickhouse_client(_clickhouse_url)).append(
        tenant,
        [
            UsageEvent(
                id=UsageEventId("u_e2e_1"),
                tenant_id=tenant,
                customer_id="cus_e2e",
                metric="api_calls",
                quantity=Decimal("100"),
                occurred_at=datetime(2026, 1, 15, tzinfo=UTC),
            )
        ],
    )

    # ── Reconcile via the API; the eager worker persists the auditable run (§3, decision C) ──
    accepted = client.post("/api/v1/reconciliations", headers=AUTH, json={"window": JAN_JSON})
    assert accepted.status_code == 202, accepted.text
    job = client.get(f"/api/v1/jobs/{accepted.json()['job_id']}", headers=AUTH).json()
    assert job["status"] == "succeeded", job
    assert job["result_type"] == "reconciliation"
    reconciliation_id = job["result_ref"]

    recon = client.get(f"/api/v1/reconciliations/{reconciliation_id}", headers=AUTH).json()
    assert recon["total_leakage"] == {"amount": "10.00", "currency": "USD"}
    assert recon["finding_count"] == 1
    assert recon["rule_version"] == "reconciliation-v1"
    listing = client.get("/api/v1/reconciliations", headers=AUTH).json()
    assert reconciliation_id in [r["id"] for r in listing["items"]]

    # ── Finding lifecycle through the four explicit routes (decision D) ──
    findings = client.get(
        f"/api/v1/findings?reconciliation_id={reconciliation_id}", headers=AUTH
    ).json()
    assert len(findings["items"]) == 1
    finding = findings["items"][0]
    assert finding["status"] == "new"
    assert finding["amount"] == {"amount": "10.00", "currency": "USD"}
    assert finding["explanation"].strip()
    finding_id = finding["id"]

    for action, expected in (("review", "reviewed"), ("confirm", "confirmed"), ("recover", "recovered")):
        response = client.post(f"/api/v1/findings/{finding_id}/{action}", headers=AUTH)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == expected  # $10.00 ends RECOVERED

    illegal = client.post(f"/api/v1/findings/{finding_id}/dismiss", headers=AUTH)
    assert illegal.status_code == 409
    assert illegal.json()["error"]["code"] == "invalid_finding_transition"
```

- [ ] **Step 3: Run the E2E (Docker must be running)**

Run: `uv run pytest tests/e2e -q -m integration`
Expected: `2 passed` (or `2 skipped` without Docker). If the eager task fails, the
exception propagates into the request (`task_eager_propagates=True`) — debug the real
cause; do not weaken assertions.

- [ ] **Step 4: Confirm the rest of the Docker suite still passes**

Run: `uv run pytest tests/integration -q -m integration`
Expected: `16 passed, 1 skipped` (unchanged from 3A/3B).

- [ ] **Step 5: Commit**

```bash
git add backend/tests/e2e/conftest.py backend/tests/e2e/test_money_path.py
git commit -m "test(e2e): register->ingest->reconcile->lifecycle money path via the API (§12)"
```

---

## Task 15: Full 3C verification gate

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

> Count note: 174 unit tests were green at the 3B tip. 3C adds 67 (Task 1: 7, Task 2: 7, Task 3: 8, Task 4: 3, Task 5: 5, Task 6: 6, Task 7: 5, Task 8: 10, Task 9: 4, Task 10: 6, Task 11: 1, Task 12: 3, Task 13: 2) → expect **241 passed**. Review fixes during execution may add more; the gate is that ALL pass.

- [ ] **Step 2: Verify the OpenAPI contract is current**

Run from `backend/`:
```bash
uv run python ../ops/scripts/export_openapi.py --check
git status --short
```
Expected: `OpenAPI contract is up to date.`; clean working tree.

- [ ] **Step 3: Run the full Docker-backed suite (integration + E2E)**

Ensure Docker Desktop is running, then from `backend/`:
```bash
uv run pytest tests/integration tests/e2e -q -m integration
```
Expected: `18 passed, 1 skipped` — the 16 prior integration tests, the 2 new E2E tests, and the one env-gated live-Stripe skip.

- [ ] **Step 4: Confirm and report**

3C is complete when Steps 1–3 are green. Report: the `/api/v1` surface (connectors,
ingestion, reconciliations, findings + four transitions, jobs), signature-routed webhooks,
`run_as_job` + the three Celery tasks, the extended `/ready`, and the committed OpenAPI
contract with its CI drift guard are in place — **Slice 3 is done**: stop and report per
the spec's Definition of Done (§17).

---

## Assumptions (named, not silent)

1. **Webhook re-pull window = trailing 24h** (`REPULL_LOOKBACK`, Task 9). Spec §6 mandates "an idempotent re-pull of the affected window" without parsing payloads this slice; a fixed recent lookback is the minimal faithful reading — idempotent ingestion (§8) makes overshoot safe. Per-event-type windows arrive with payload parsing (future work).
2. **Webhooks are not flag-gated at the route.** A 403 would make the provider mark the endpoint broken; the verified event is accepted (202) and the worker task enforces `ingestion_enabled`, failing the Job visibly when off (§16 defense-in-depth).
3. **Cursor pagination is offset-encoded internally** (Task 3). The wire contract is opaque-cursor (stable for Slice 4); 3A repositories expose full `list_*` reads, so the cursor encodes an offset this slice. Keyset pagination is a drop-in replacement inside `pagination.py` later.
4. **`Stripe-Signature` is read directly** while STRIPE_BILLING is the only connector type; per-type signature-header resolution lands with a second connector (§17 seam noted in the webhook router docstring).
5. **`connector_base_url` is a new setting** (Task 3): the composition roots need a config-driven way to aim connectors at stripe-mock (tests/CI) vs. live Stripe. Unset in production. Documented in `.env.example` (§16).
6. **Ingestion tasks re-check the flag with a plain `RuntimeError`** rather than importing the API-layer `IngestionDisabledError` (workers don't import `api`); the Job's `error` string carries the reason.
7. **E2E seeds plans/contracts/invoices/usage through the 3A stores** where no API exists yet (Slice 4, spec §0) and because stripe-mock's canned data can't drive deterministic dollar assertions (nor does it implement Billing meter event summaries). Every surface 3C builds is exercised through the API.
8. **`handlers.py` imports the `ConnectorAuthError` TYPE** (only) from infrastructure — required by the spec's own §5.4 mapping table; documented inline as the sanctioned exception to "only `dependencies/` imports infrastructure".

## Dependencies on 3A/3B (must already exist — they do, at the 3B tip)

- 3B use-cases + `EntityNotFoundError` (consumed by routers/workers exactly as published in Plan 3B's "Interfaces Plan 3C will consume" table).
- 3A: `Job` model + repository, connector store/registration/cipher, idempotent saves, migration `0002`, engine/session + ClickHouse client factories, `Settings` keys (`api_tokens`, `ingestion_enabled`, `credentials_key`).
- Slice 0/2: app factory + envelope, Celery app (`task_acks_late`), Stripe connector (`verify_webhook` + 300s tolerance), testcontainers conftest patterns.

## What Slice 4 consumes from 3C (the public surface this plan produces)

- **`contracts/openapi/openapi.json`** — the canonical, CI-guarded schema the typed frontend client generates from (§10).
- The `/api/v1` REST surface itself: bearer auth (`api_tokens` now; OIDC slots into `dependencies/auth.py` later), the `{ error: { code, message, details } }` envelope, opaque-cursor pagination, `202 {job_id}` → `GET /jobs/{job_id}` polling, money as `{amount: string, currency}`.
- Worker task names (`yieldfield.run_reconciliation`, `yieldfield.ingest_invoices`, `yieldfield.ingest_usage_events`) — the API↔worker contract pinned by `test_worker_tasks.py`.

## Recommended execution order & verification gates

Tasks are ordered by dependency and must run sequentially: **1 → 2 → 3** (error surface → DTOs → dependencies: everything else builds on these) → **4 → 5 → 6 → 7 → 8** (routers; Task 6 also adds the `JobSubmitter` seam Tasks 7/9 reuse) → **9** (webhooks) → **10 → 11** (job wrapper, then the tasks that wrap with it) → **12** (/ready) → **13** (OpenAPI last among code tasks — the schema must include every route) → **14** (E2E composes everything) → **15** (gate).

Per-task gates: each task ends with its own tests green + `mypy` + (where named) `ruff`/`black`/`lint-imports`. Plan-level gates: Task 15 Steps 1–3 (static + unit, contract check, Docker integration + E2E). After Task 15, run the final whole-implementation review, then **Slice 3 stops and reports** (spec §17) — no Slice 4 work.

