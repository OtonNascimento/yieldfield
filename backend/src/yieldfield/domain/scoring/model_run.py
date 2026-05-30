"""ModelRun (§8 glossary, §12) — the versioned, reproducible identity of a scoring run.

A finding references the exact ModelRun that produced its confidence, so any score is
reconstructable (§6.5 lineage). The concrete model code lives in
`infrastructure/scoring_engine/` (Slice 5); this is just the run's identity + params.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from yieldfield.domain.shared.errors import InvalidEntityError
from yieldfield.domain.shared.ids import ModelRunId


@dataclass(frozen=True, slots=True)
class ModelRun:
    id: ModelRunId
    model_name: str
    model_version: str
    created_at: datetime
    params: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.model_name.strip():
            raise InvalidEntityError("ModelRun model_name is required.")
        if not self.model_version.strip():
            raise InvalidEntityError("ModelRun model_version is required.")
        if self.created_at.tzinfo is None:
            raise InvalidEntityError("ModelRun created_at must be timezone-aware.")
