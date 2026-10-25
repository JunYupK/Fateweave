"""Auth, Host/Origin allowlist, log hygiene and bind defaults for the remote MCP endpoint."""

import logging
from datetime import date

import pytest
from helpers import valid_draft
from mcp_http import (
    MCP_HOST,
    MCP_KEY,
    MCPClient,
    initialize_payload,
    mcp_settings,
    running_app,
    services_for,
)
from sqlalchemy.ext.asyncio import AsyncEngine
from uvicorn.logging import AccessFormatter

from fateweave.config import Settings
from fateweave.models.facts import PreparedAnalysis
from fateweave.storage.db import make_sessionmaker

BIRTH_DATE = "1987-11-23"
PROFILE = {
    "birth_date": BIRTH_DATE,
    "calendar": "solar",
    "birth_time": "09:15:00",
    "gender_for_daewoon": "male",
    "longitude": 127.0,
}


def _assert_unauthorized(resp) -> None:
    assert resp.status_code == 401
    assert resp.json() == {"error": "unauthorized"}
    assert "www-authenticate" not in resp.headers
    assert "mcp-session-id" not in resp.headers


async def test_missing_or_wrong_key_denied():
    async with running_app() as http:
        anon = MCPClient(http, key=None)
        _assert_unauthorized(await anon.post(initialize_payload()))
        wrong = MCPClient(http, key=MCP_KEY + "x")
        _assert_unauthorized(await wrong.post(initialize_payload()))
        _assert_unauthorized(await MCPClient(http, key="").post(initialize_payload()))
        # the key is never accepted from the query string
        resp = await http.post(
            f"/mcp?x-fateweave-key={MCP_KEY}&key={MCP_KEY}",
            json=initialize_payload(),
            headers=anon.headers(),
        )
        _assert_unauthorized(resp)

        ok = MCPClient(http)
        await ok.initialize()
        sid = ok.session_id
        for method in ("GET", "DELETE"):
            resp = await http.request(
                method,
                "/mcp",
                headers={"mcp-session-id": sid, "accept": "text/event-stream"},
            )
            _assert_unauthorized(resp)
            resp = await http.request(
                method,
                "/mcp",
                headers={"mcp-session-id": sid, "x-fateweave-key": "nope"},
            )
            _assert_unauthorized(resp)
        # the authenticated session still works afterwards
        tools = (await ok.request("tools/list"))["tools"]
        assert len(tools) == 5
        resp = await http.delete("/mcp", headers=ok.headers())
        assert resp.status_code == 200


async def test_nonlisted_host_denied():
    async with running_app() as http:
        client = MCPClient(http)
        for host in ("evil.example", f"{MCP_HOST}.evil.example", f"{MCP_HOST}:8080"):
            resp = await client.post(initialize_payload(), host=host)
            assert resp.status_code != 200 and resp.status_code in (400, 403, 421), host
            assert "mcp-session-id" not in resp.headers

        resp = await client.post(initialize_payload(), origin="https://evil.example")
        assert resp.status_code in (400, 403, 421)

        for origin in ("https://claude.ai", "https://claude.com", f"https://{MCP_HOST}"):
            resp = await client.post(initialize_payload(), origin=origin)
            assert resp.status_code == 200, origin
        resp = await client.post(initialize_payload(), host=f"{MCP_HOST}:443")
        assert resp.status_code == 200

    async with running_app() as http:  # an absent Origin (server-to-server) is allowed
        await MCPClient(http).initialize()


async def test_secrets_and_birthdates_absent_from_access_logs(
    engine: AsyncEngine, caplog: pytest.LogCaptureFixture
):
    caplog.set_level(logging.DEBUG)
    for name in (
        "uvicorn",
        "uvicorn.access",
        "uvicorn.error",
        "mcp",
        "sqlalchemy",
        "sqlalchemy.engine",
        "sse_starlette",
        "httpx",
        "fateweave",
    ):
        caplog.set_level(logging.DEBUG, logger=name)

    services = services_for(make_sessionmaker(engine), clock=lambda: date(2026, 10, 25))
    async with running_app(services) as http:
        client = MCPClient(http)
        await client.initialize()
        result = await client.call_tool(
            "prepare_analysis", {"mode": "individual", "profiles": [PROFILE]}
        )
        prepared = PreparedAnalysis.model_validate(result["structuredContent"])
        assert prepared.facts["self"].solar_date == BIRTH_DATE  # the data did flow through
        final = await client.call_tool(
            "finalize_report",
            {
                "analysis_id": str(prepared.analysis_id),
                "draft": valid_draft(prepared).model_dump(mode="json"),
                "idempotency_key": "log-key-1",
            },
        )
        assert final["structuredContent"]["status"] == "FINALIZED"
        _assert_unauthorized(await MCPClient(http, key=MCP_KEY[:-1]).post(initialize_payload()))

    names = {r.name for r in caplog.records}
    assert "sqlalchemy.engine.Engine" in names  # SQL was logged, with parameters hidden
    assert any(n.startswith("mcp.") for n in names)
    text = "\n".join(
        f"{r.name} {r.getMessage()} {r.exc_text or ''} {r.stack_info or ''}" for r in caplog.records
    )
    assert MCP_KEY not in text and MCP_KEY[:-1] not in text
    assert BIRTH_DATE not in text and "09:15" not in text
    assert "auth failed" in text


def test_redaction_filter_scrubs_key_from_any_record():
    from fateweave.mcp.auth import RedactionFilter

    flt = RedactionFilter(MCP_KEY)
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',  # uvicorn's access record shape
        ("127.0.0.1:5000", "POST", f"/mcp?key={MCP_KEY}", "1.1", 401),
        None,
    )
    assert flt.filter(record)
    assert MCP_KEY not in record.getMessage()
    # uvicorn's access formatter unpacks record.args: the filter must keep their shape
    line = AccessFormatter('%(client_addr)s "%(request_line)s" %(status_code)s').format(record)
    assert line == '127.0.0.1:5000 "POST /mcp?key=[REDACTED] HTTP/1.1" 401 Unauthorized'
    header = logging.LogRecord(
        "x",
        logging.INFO,
        __file__,
        1,
        "headers: %r",
        ({"X-Fateweave-Key": "other-value"},),
        None,
    )
    flt.filter(header)
    assert "other-value" not in header.getMessage()


def test_direct_app_port_not_public_in_test_config(monkeypatch):
    for name in ("FATEWEAVE_BIND_HOST", "FATEWEAVE_PORT"):
        monkeypatch.delenv(name, raising=False)
    defaults = Settings(
        _env_file=None, database_url="postgresql+asyncpg://u@h/db", mcp_key="k", public_host="h"
    )
    assert defaults.bind_host == "127.0.0.1"
    assert defaults.port == 8080
    assert mcp_settings().bind_host == "127.0.0.1"

    import fateweave.__main__ as entry

    custom = defaults.model_copy(update={"bind_host": "10.1.2.3", "port": 9123})
    calls: list[tuple[tuple, dict]] = []
    monkeypatch.setattr(entry, "get_settings", lambda: custom)
    monkeypatch.setattr(entry.uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))
    entry.main()
    ((args, kwargs),) = calls
    assert kwargs["host"] == "10.1.2.3" and kwargs["port"] == 9123
    assert kwargs.get("access_log", True) is True


async def test_mcp_path_is_exact_without_redirects():
    async with running_app() as http:
        authed = MCPClient(http)
        for headers in (authed.headers(), MCPClient(http, key=None).headers()):
            resp = await http.post("/mcp/", json=initialize_payload(), headers=headers)
            assert not 300 <= resp.status_code < 400, resp.status_code
            assert resp.status_code in (401, 404)
            assert "location" not in resp.headers
        for path in ("/mcp/mcp", "/mcpfoo"):
            resp = await http.post(path, json=initialize_payload(), headers=authed.headers())
            assert resp.status_code == 404, path
            assert "location" not in resp.headers
        for method in ("HEAD", "OPTIONS"):
            resp = await http.request(method, "/mcp")
            assert resp.status_code == 401, method
            assert "mcp-session-id" not in resp.headers
