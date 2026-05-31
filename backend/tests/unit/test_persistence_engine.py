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


def test_plan_repo_rejects_tenant_mismatch_before_touching_db() -> None:
    from yieldfield.domain.billing.plan import Plan
    from yieldfield.domain.shared.ids import PlanId, TenantId
    from yieldfield.domain.shared.money import Money
    from yieldfield.infrastructure.persistence.errors import PersistenceError
    from yieldfield.infrastructure.persistence.repositories import SqlAlchemyPlanRepository

    repo = SqlAlchemyPlanRepository(session=None)  # type: ignore[arg-type]  # guard runs before any session use
    plan = Plan(
        id=PlanId("pl_1"),
        tenant_id=TenantId("t_OTHER"),
        name="p",
        metric="m",
        unit_price=Money.of("1", "USD"),
    )
    with pytest.raises(PersistenceError, match="does not match"):
        repo.add(TenantId("t_1"), plan)
