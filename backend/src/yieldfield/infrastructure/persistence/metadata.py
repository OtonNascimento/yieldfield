"""Alembic metadata glue (§12). Exposes the declarative metadata for migrations."""

from __future__ import annotations

from sqlalchemy import MetaData

from yieldfield.infrastructure.persistence.models import Base

metadata: MetaData = Base.metadata
