"""FastAPI app: `GET /healthz` plus the authenticated MCP Streamable HTTP endpoint at `/mcp`.

Settings, the database engine and the MCP server are built in the lifespan, so importing this
module (and `GET /healthz`) never needs secrets.
"""

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from fateweave.config import Settings, get_settings
from fateweave.mcp.auth import MCPKeyAuthMiddleware, log_hygiene
from fateweave.mcp.server import ServiceContainer, create_mcp_server
from fateweave.services.analysis import AnalysisService
from fateweave.services.reports import ReportService
from fateweave.storage.db import make_engine, make_sessionmaker

MCP_PATH = "/mcp"
CLAUDE_ORIGINS = ("https://claude.ai", "https://claude.com")


def transport_security(settings: Settings) -> TransportSecuritySettings:
    host = settings.public_host
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[host, f"{host}:443"],
        # An absent Origin (Claude's server-to-server calls) is allowed by the SDK.
        allowed_origins=[*CLAUDE_ORIGINS, f"https://{host}"],
    )


class _MCPEndpoint:
    """ASGI endpoint for `/mcp`; delegates to the authenticated MCP app once the lifespan runs."""

    def __init__(self) -> None:
        self.app: ASGIApp | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.app is None:
            await JSONResponse({"error": "unavailable"}, status_code=503)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_app(
    settings: Settings | None = None, services: ServiceContainer | None = None
) -> FastAPI:
    endpoint = _MCPEndpoint()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        cfg = settings or get_settings()
        async with AsyncExitStack() as stack:
            svc = services
            if svc is None:
                engine = make_engine(cfg.database_url)
                stack.push_async_callback(engine.dispose)
                sm = make_sessionmaker(engine)
                svc = ServiceContainer(analysis=AnalysisService(sm), reports=ReportService(sm))
            server = create_mcp_server(svc)
            # The SDK app routes exactly MCP_PATH; it is served from our single `/mcp` route.
            mcp_app = server.streamable_http_app(
                streamable_http_path=MCP_PATH, transport_security=transport_security(cfg)
            )
            stack.enter_context(log_hygiene(cfg.mcp_key))
            await stack.enter_async_context(server.session_manager.run())
            endpoint.app = MCPKeyAuthMiddleware(mcp_app, cfg.mcp_key)
            try:
                yield
            finally:
                endpoint.app = None

    # redirect_slashes=False: `/mcp/` is a plain 404, never a 307 to `/mcp` (exact path only).
    app = FastAPI(title="Fateweave", lifespan=lifespan, redirect_slashes=False)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "fateweave"}

    app.router.add_route(MCP_PATH, endpoint, include_in_schema=False)
    return app


app = create_app()
