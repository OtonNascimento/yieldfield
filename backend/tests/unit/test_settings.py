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


def test_production_boot_fails_fast_listing_every_missing_key() -> None:
    # Misconfiguration must fail at BOOT, not on the first request (§16, audit PR-1).
    with pytest.raises(ValueError, match="Production misconfiguration") as excinfo:
        Settings(_env_file=None, environment="production")
    message = str(excinfo.value)
    for key in (
        "YIELDFIELD_DATABASE_URL",
        "YIELDFIELD_CLICKHOUSE_URL",
        "YIELDFIELD_CREDENTIALS_KEY",
        "YIELDFIELD_API_TOKENS",
        "YIELDFIELD_LOG_JSON=true",
    ):
        assert key in message


def test_fully_configured_production_boots() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        database_url="postgresql://u:p@db:5432/yieldfield",
        clickhouse_url="http://u:p@ch:8123/yieldfield",
        credentials_key="some-fernet-key",
        api_tokens={"tok": "tenant-1"},
        log_json=True,
    )
    assert settings.is_production is True


def test_production_rejects_debug_and_connector_base_url() -> None:
    # debug=True leaks tracebacks; connector_base_url must never redirect live pulls (§16).
    with pytest.raises(ValueError, match="Production misconfiguration") as excinfo:
        Settings(
            _env_file=None,
            environment="production",
            database_url="postgresql://u:p@db:5432/yieldfield",
            clickhouse_url="http://u:p@ch:8123/yieldfield",
            credentials_key="some-fernet-key",
            api_tokens={"tok": "tenant-1"},
            log_json=True,
            debug=True,
            connector_base_url="http://mock",
        )
    message = str(excinfo.value)
    assert "YIELDFIELD_DEBUG=false" in message
    assert "YIELDFIELD_CONNECTOR_BASE_URL unset" in message


def test_non_production_environments_keep_permissive_defaults() -> None:
    for environment in ("local", "ci", "staging"):
        settings = Settings(_env_file=None, environment=environment)
        assert settings.database_url is None  # no boot-time requirement outside production
