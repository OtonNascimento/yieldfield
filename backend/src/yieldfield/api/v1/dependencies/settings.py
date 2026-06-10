"""Settings as a FastAPI dependency — one override point for every test (§16)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from yieldfield.config.settings import Settings, get_settings


def get_app_settings() -> Settings:
    return get_settings()


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
