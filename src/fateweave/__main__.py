"""`python -m fateweave`: serve the app with uvicorn on settings.bind_host:settings.port.

The access log stays on; the app lifespan attaches the redaction filter to uvicorn's handlers.
"""

import uvicorn

from fateweave.api import create_app
from fateweave.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        create_app(settings),
        host=settings.bind_host,
        port=settings.port,
        access_log=True,
        proxy_headers=settings.proxy_headers,
        forwarded_allow_ips=settings.forwarded_allow_ips,
    )


if __name__ == "__main__":
    main()
