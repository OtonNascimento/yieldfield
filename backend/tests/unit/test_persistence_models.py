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
    for name in (
        "plans",
        "contracts",
        "invoices",
        "invoice_line_items",
        "reconciliations",
        "findings",
    ):
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
