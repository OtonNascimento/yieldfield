"""Settings load and validate at boot (§16 fail-fast config)."""

from __future__ import annotations

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
