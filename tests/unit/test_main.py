from fateweave import __main__ as entry
from fateweave.config import Settings


def test_main_passes_proxy_settings_to_uvicorn(monkeypatch):
    settings = Settings(
        database_url="postgresql+asyncpg://u@h/db",
        mcp_key="k",
        public_host="example.test",
        bind_host="0.0.0.0",
        port=9090,
        forwarded_allow_ips="10.0.0.1",
        proxy_headers=True,
        _env_file=None,
    )
    captured = {}
    monkeypatch.setattr(entry, "get_settings", lambda: settings)
    monkeypatch.setattr(entry, "create_app", lambda s: "app")
    monkeypatch.setattr(entry.uvicorn, "run", lambda app, **kw: captured.update(app=app, **kw))
    entry.main()
    assert captured["app"] == "app"
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9090
    assert captured["proxy_headers"] is True
    assert captured["forwarded_allow_ips"] == "10.0.0.1"


def test_proxy_defaults_trust_only_loopback():
    s = Settings(database_url="x", mcp_key="k", public_host="h", _env_file=None)
    assert s.proxy_headers is True
    assert s.forwarded_allow_ips == "127.0.0.1"
