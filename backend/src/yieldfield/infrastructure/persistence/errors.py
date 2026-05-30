"""Persistence-layer errors. Infrastructure concern — not a domain error (§6.1)."""

from __future__ import annotations


class PersistenceError(Exception):
    """Raised on a persistence misuse: missing config, tenant mismatch, precision loss."""
