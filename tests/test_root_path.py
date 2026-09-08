"""The /api prefix lives in exactly one place — a Settings.root_path fed to
FastAPI's root_path (docs/w6-decisions.md #6). Dev runs with it empty (Next
rewrites proxy the bare API); prod sets ROOT_PATH=/api so the ALB can
path-route without a rewrite."""

import pytest
from fastapi import FastAPI

from app.config import get_settings
from app.main import create_app


@pytest.fixture
def clear_settings_cache():
    yield
    get_settings.cache_clear()


def test_root_path_defaults_to_empty(monkeypatch, clear_settings_cache) -> None:
    monkeypatch.delenv("ROOT_PATH", raising=False)
    get_settings.cache_clear()
    app: FastAPI = create_app()
    assert app.root_path == ""


def test_root_path_comes_from_settings_env(monkeypatch, clear_settings_cache) -> None:
    monkeypatch.setenv("ROOT_PATH", "/api")
    get_settings.cache_clear()
    app: FastAPI = create_app()
    assert app.root_path == "/api"
