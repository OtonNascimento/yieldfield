"""Typed application settings, loaded and validated once at startup (§16).

Twelve-factor config: every value comes from the environment. Invalid or missing
required config raises at boot (fail-fast) rather than surfacing as a runtime error
deep in a money path. Secrets are never committed — `.env.example` documents the
keys with no values, and production supplies them from a secrets manager (§11, §16).

Persistence/columnar settings are intentionally optional in Slice 0 (no I/O yet);
they become required in Slice 2 when the adapters that need them land.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "ci", "staging", "production"]


class Settings(BaseSettings):
    """Validated, immutable view of the process environment (§16)."""

    model_config = SettingsConfigDict(
        env_prefix="YIELDFIELD_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        # Compose/k8s pass-throughs surface unset vars as EMPTY strings; treat those
        # exactly like absent vars (twelve-factor) instead of failing to JSON-decode
        # complex fields (api_tokens) at boot.
        env_ignore_empty=True,
    )

    # ── Application ──────────────────────────────────────────────────────────
    app_name: str = "yieldfield-api"
    environment: Environment = "local"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    # Emit human-readable logs locally, structured JSON everywhere else.
    log_json: bool = False

    # ── HTTP adapter ─────────────────────────────────────────────────────────
    api_host: str = (
        "0.0.0.0"  # noqa: S104 — binds inside the container; edge is fronted by the platform.
    )
    api_port: int = 8000
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # ── Async backbone (Celery + Redis, §13) ─────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Datastores (§12) — wired in Slice 2; optional until then ─────────────
    database_url: str | None = None  # PostgreSQL OLTP (source of truth)
    clickhouse_url: str | None = None  # ClickHouse OLAP (usage events at scale)

    # ── Connector credentials & auth (§11, §16) — required when used ──────────
    # Fernet key for the credential cipher; required only when a connector is
    # registered/used (built lazily; fails fast there if absent).
    credentials_key: str | None = None
    # Bearer-token → tenant_id map backing the request auth dependency (Plan 3C).
    # Parsed from a JSON object in YIELDFIELD_API_TOKENS.
    api_tokens: dict[str, str] = Field(default_factory=dict)
    # Feature flag gating live billing-platform pulls (DoD: risky work behind a flag).
    ingestion_enabled: bool = False
    # Optional base-URL override for billing-platform connectors (stripe-mock in tests/CI;
    # unset in production so connectors hit the real platform) (§16, §17).
    connector_base_url: str | None = None

    @property
    def celery_broker_url(self) -> str:
        """Celery broker URL — Redis in the local/CI stack (ADR-0001)."""
        return self.redis_url

    @property
    def celery_result_backend(self) -> str:
        """Celery result backend — Redis in the local/CI stack (ADR-0001)."""
        return self.redis_url

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def _production_invariants(self) -> Settings:
        """Fail at boot, not on the first request, when production is misconfigured (§16).

        Datastores/auth/cipher are optional in local/CI (no I/O required to import the
        app); in production their absence is a deploy error and must stop the boot.
        """
        if self.environment != "production":
            return self
        checks: list[tuple[str, bool]] = [
            ("YIELDFIELD_DATABASE_URL", bool(self.database_url)),
            ("YIELDFIELD_CLICKHOUSE_URL", bool(self.clickhouse_url)),
            ("YIELDFIELD_CREDENTIALS_KEY", bool(self.credentials_key)),
            ("YIELDFIELD_API_TOKENS", bool(self.api_tokens)),
            ("YIELDFIELD_LOG_JSON=true", self.log_json),
            ("YIELDFIELD_DEBUG=false", not self.debug),
            ("YIELDFIELD_CONNECTOR_BASE_URL unset", self.connector_base_url is None),
        ]
        problems = [name for name, ok in checks if not ok]
        if problems:
            raise ValueError(f"Production misconfiguration: {', '.join(problems)} (§16).")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton, building it on first call.

    Cached so config is parsed and validated exactly once. Call this at boot (app
    factory, worker startup) so misconfiguration fails fast before serving traffic.
    """
    return Settings()
