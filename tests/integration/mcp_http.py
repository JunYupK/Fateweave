"""In-process helpers: drive create_app() over real Streamable HTTP JSON-RPC (ASGITransport)."""

import contextlib
import json
import secrets
from collections.abc import AsyncIterator

import httpx

from fateweave.api import create_app
from fateweave.config import Settings
from fateweave.mcp.server import ServiceContainer
from fateweave.services.analysis import AnalysisService
from fateweave.services.reports import ReportService
from fateweave.storage.db import make_engine, make_sessionmaker

MCP_KEY = "test-mcp-key-" + secrets.token_hex(8)
MCP_HOST = "testserver"
PROTOCOL_VERSION = "2025-11-25"


def mcp_settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://unused:unused@127.0.0.1:1/unused",
        mcp_key=MCP_KEY,
        public_host=MCP_HOST,
    )


def services_for(sessionmaker, clock=None) -> ServiceContainer:
    analysis = AnalysisService(sessionmaker, clock) if clock else AnalysisService(sessionmaker)
    return ServiceContainer(analysis=analysis, reports=ReportService(sessionmaker))


def parse_body(resp: httpx.Response) -> dict:
    """The JSON-RPC response from a JSON or SSE (text/event-stream) reply."""
    if resp.headers.get("content-type", "").startswith("text/event-stream"):
        events = [
            json.loads(line[len("data:") :])
            for line in resp.text.splitlines()
            if line.startswith("data:") and line[len("data:") :].strip()
        ]
        return next(e for e in events if "id" in e)
    return resp.json()


def initialize_payload() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "fateweave-test", "version": "0"},
        },
    }


class MCPClient:
    """Minimal MCP client: initialize handshake, then JSON-RPC requests on the session."""

    def __init__(self, http: httpx.AsyncClient, key: str | None = MCP_KEY, path: str = "/mcp"):
        self.http = http
        self.key = key
        self.path = path
        self.session_id: str | None = None
        self._next_id = 0

    def headers(self, **extra: str) -> dict[str, str]:
        h = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
        if self.key is not None:
            h["x-fateweave-key"] = self.key
        if self.session_id is not None:
            h["mcp-session-id"] = self.session_id
        h["mcp-protocol-version"] = PROTOCOL_VERSION
        h.update(extra)
        return h

    async def post(self, payload: dict, **extra_headers: str) -> httpx.Response:
        return await self.http.post(self.path, json=payload, headers=self.headers(**extra_headers))

    async def initialize(self) -> dict:
        resp = await self.post(initialize_payload())
        assert resp.status_code == 200, resp.status_code
        # Stateless server: no session id is issued (requests are independent).
        self.session_id = resp.headers.get("mcp-session-id")
        result = parse_body(resp)["result"]
        ack = await self.post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert ack.status_code == 202, ack.status_code
        return result

    async def request(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        payload: dict = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            payload["params"] = params
        resp = await self.post(payload)
        assert resp.status_code == 200, resp.status_code
        body = parse_body(resp)
        assert "error" not in body, body
        return body["result"]

    async def call_tool(self, name: str, arguments: dict) -> dict:
        return await self.request("tools/call", {"name": name, "arguments": arguments})


@contextlib.asynccontextmanager
async def running_app(
    services: ServiceContainer | None = None, settings: Settings | None = None
) -> AsyncIterator[httpx.AsyncClient]:
    """Run create_app()'s lifespan and yield an httpx client bound to it in-process."""
    settings = settings or mcp_settings()
    if services is None:  # engines are lazy: this never connects
        services = services_for(make_sessionmaker(make_engine(settings.database_url)))
    app = create_app(settings=settings, services=services)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=f"http://{MCP_HOST}") as http:
            yield http
