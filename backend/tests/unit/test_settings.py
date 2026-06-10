"""Settings load and validate at boot (§16 fail-fast config)."""

from __future__ import annotations

import pytest

from yieldfield.config.settings import Settings


def test_defaults_are_valid() -> None:
    settings = Settings()
    assert settings.app_name == "yieldfield-api"
    assert settings.environment == "local"
    # Celery broker/backend derive from the single Redis URL (ADR-0001).
    assert settings.celery_broker_url == settings.redis_url
    assert settings.celery_result_backend == settings.redis_url


def test_environment_override(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("YIELDFIELD_ENVIRONMENT", "staging")
    monkeypatch.setenv("YIELDFIELD_LOG_LEVEL", "WARNING")
    settings = Settings()
    assert settings.environment == "staging"
    assert settings.log_level == "WARNING"
    assert settings.is_production is False


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


def test_connector_base_url_defaults_to_none() -> None:
    settings = Settings(_env_file=None)
    assert settings.connector_base_url is None
