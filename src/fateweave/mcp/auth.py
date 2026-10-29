"""Personal-use auth for `/mcp`: a fixed `X-Fateweave-Key` header, plus log redaction.

The key is accepted from the request header, or as the last path segment of `/mcp/<key>` for
clients that cannot send custom headers (Claude custom connectors take only a URL). It is never
accepted from the query string, and is compared in constant time. Failures log only
"auth failed": no header values, no paths, no request bodies.
"""

import contextlib
import hmac
import logging
import re
from collections.abc import Iterator

from pydantic import SecretStr
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

log = logging.getLogger(__name__)

KEY_HEADER = b"x-fateweave-key"
REDACTED = "[REDACTED]"
_HEADER_VALUE = re.compile(r"""(x-fateweave-key['"]?\s*[:=,]\s*['"]?)[^\s'",}]+""", re.IGNORECASE)
# Any segment after `/mcp/`: a wrong or near-miss key there is as sensitive as the key.
_PATH_KEY = re.compile(r"(/mcp/)[^\s/?#\"']+")


class MCPKeyAuthMiddleware:
    """ASGI wrapper: every HTTP request must carry the exact key, in `X-Fateweave-Key` on `path`
    or as the path itself (`<path>/<key>`).

    A wrong path key is answered like any unknown path (plain 404), so the key-in-path form does
    not reveal that it exists. Authorized key-in-path requests reach `app` with the path
    rewritten to `path`.
    """

    def __init__(self, app: ASGIApp, key: SecretStr, path: str = "/mcp") -> None:
        secret = key.get_secret_value().encode("utf-8")
        if not secret:
            raise ValueError("mcp_key must not be empty")
        self._app = app
        self._key = secret
        self._path = path
        self._prefix = path + "/"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith(self._prefix):
            provided = scope["path"][len(self._prefix) :].encode("utf-8")
            if not hmac.compare_digest(provided, self._key):
                log.warning("auth failed")
                await PlainTextResponse("Not Found", status_code=404)(scope, receive, send)
                return
            scope = {**scope, "path": self._path, "raw_path": self._path.encode("ascii")}
            await self._app(scope, receive, send)
            return
        if scope["type"] == "http" and not self._authorized(scope):
            log.warning("auth failed")
            response = JSONResponse({"error": "unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)

    def _authorized(self, scope: Scope) -> bool:
        provided = [value for name, value in scope["headers"] if name == KEY_HEADER]
        if len(provided) != 1:
            return False
        return hmac.compare_digest(provided[0], self._key)


class RedactionFilter(logging.Filter):
    """Scrub the MCP key (anywhere, e.g. a query string in an access log) and key headers."""

    def __init__(self, secret: str) -> None:
        super().__init__()
        self._secret = secret

    def _scrub(self, text: str) -> str:
        text = _HEADER_VALUE.sub(lambda m: m.group(1) + REDACTED, text)
        text = _PATH_KEY.sub(lambda m: m.group(1) + REDACTED, text)
        return text.replace(self._secret, REDACTED) if self._secret else text

    def _clean(self, value: object) -> object:
        return self._scrub(value) if isinstance(value, str) else value

    def filter(self, record: logging.LogRecord) -> bool:
        # Scrub msg and each string arg in place: formatters such as uvicorn's AccessFormatter
        # unpack record.args, so its shape must be kept.
        if isinstance(record.msg, str):
            record.msg = self._scrub(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(self._clean(a) for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: self._clean(v) for k, v in record.args.items()}
        try:
            message = record.getMessage()
        except Exception:  # a malformed record: let logging report it as usual
            return True
        scrubbed = self._scrub(message)
        if scrubbed != message:  # the secret hid inside a non-str arg (e.g. a dict's repr)
            record.msg, record.args = scrubbed, ()
        return True


_LOGGERS = ("", "uvicorn", "uvicorn.access", "uvicorn.error")
# Loggers whose DEBUG records carry bodies: SSE response chunks, SQL result rows.
BODY_LOGGERS = ("sse_starlette", "sqlalchemy.engine")


@contextlib.contextmanager
def log_hygiene(secret: SecretStr) -> Iterator[RedactionFilter]:
    """While the app runs: redact the key on root/uvicorn handlers, never emit body records."""
    flt = RedactionFilter(secret.get_secret_value())
    handlers = {h for name in _LOGGERS for h in logging.getLogger(name).handlers}
    for handler in handlers:
        handler.addFilter(flt)
    pinned = {name: logging.getLogger(name).level for name in BODY_LOGGERS}
    for name in BODY_LOGGERS:
        logger = logging.getLogger(name)
        if logger.getEffectiveLevel() < logging.INFO:
            logger.setLevel(logging.INFO)
    try:
        yield flt
    finally:
        for name, level in pinned.items():
            logging.getLogger(name).setLevel(level)
        for handler in handlers:
            handler.removeFilter(flt)
