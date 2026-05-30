"""LeakageType (§8) — the kinds of revenue leakage Yieldfield detects (§1, §4 CORE).

New leakage types are added here as typed strategies, not as scattered conditionals
(§17). Slice 1 reconciliation rules detect `unbilled_usage` and `misrated_line_item`;
`unaudited_adjustment` is part of the model and gets its own rule in a later slice.
"""

from __future__ import annotations

from enum import StrEnum


class LeakageType(StrEnum):
    # Usage events that occurred but were never billed.
    UNBILLED_USAGE = "unbilled_usage"
    # An invoice line item billed an amount that disagrees with the plan's rating.
    MISRATED_LINE_ITEM = "misrated_line_item"
    # A manual adjustment that reduced revenue and was never audited.
    UNAUDITED_ADJUSTMENT = "unaudited_adjustment"
