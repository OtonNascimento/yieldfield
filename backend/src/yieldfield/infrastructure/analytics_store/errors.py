"""Analytics-store (OLAP) errors. Infrastructure concern, not a domain error (§6.1)."""

from __future__ import annotations


class AnalyticsStoreError(Exception):
    """Raised on an OLAP misuse: missing config or tenant-scope violation."""
