import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fateweave.api import app
from fateweave.config import Settings, get_settings

SECRET = "super-secret-key-123"


def test_healthz_is_app_scoped():
    resp = TestClient(app).get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "fateweave"}


def test_required_secret_is_rejected_when_missing(monkeypatch):
    for name in ("FATEWEAVE_DATABASE_URL", "FATEWEAVE_MCP_KEY", "FATEWEAVE_PUBLIC_HOST"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=None)
    assert "mcp_key" in str(exc.value)


def test_settings_repr_hides_key(monkeypatch):
    monkeypatch.setenv("FATEWEAVE_DATABASE_URL", "postgresql+asyncpg://u@h/db")
    monkeypatch.setenv("FATEWEAVE_MCP_KEY", SECRET)
    monkeypatch.setenv("FATEWEAVE_PUBLIC_HOST", "example.test")
    s = Settings(_env_file=None)
    assert SECRET not in repr(s)
    assert SECRET not in str(s)
    assert s.mcp_key.get_secret_value() == SECRET
    assert s.MANSE_POLICY_VERSION == "manse-v1"
    assert s.RULE_VERSION == "rules-v2"
    assert s.REPORT_SCHEMA_VERSION == "report-v1"


def test_get_settings_is_cached(monkeypatch):
    monkeypatch.setenv("FATEWEAVE_DATABASE_URL", "x")
    monkeypatch.setenv("FATEWEAVE_MCP_KEY", SECRET)
    monkeypatch.setenv("FATEWEAVE_PUBLIC_HOST", "h")
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()


def test_blank_optional_vars_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("FATEWEAVE_DATABASE_URL", "postgresql+asyncpg://u@h/db")
    monkeypatch.setenv("FATEWEAVE_MCP_KEY", SECRET)
    monkeypatch.setenv("FATEWEAVE_PUBLIC_HOST", "example.test")
    for name in (
        "FATEWEAVE_PORT",
        "FATEWEAVE_PROXY_HEADERS",
        "FATEWEAVE_BIND_HOST",
        "FATEWEAVE_FORWARDED_ALLOW_IPS",
    ):
        monkeypatch.setenv(name, "")
    s = Settings(_env_file=None)
    assert s.port == 8080
    assert s.proxy_headers is True
    assert s.bind_host == "127.0.0.1"
    assert s.forwarded_allow_ips == "127.0.0.1"
