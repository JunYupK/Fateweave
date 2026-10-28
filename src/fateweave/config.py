from functools import lru_cache
from typing import ClassVar

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # env_ignore_empty: a blank optional var (e.g. `FATEWEAVE_PORT=`) falls back to its default.
    model_config = SettingsConfigDict(
        env_prefix="FATEWEAVE_", env_file=".env", extra="ignore", env_ignore_empty=True
    )

    MANSE_POLICY_VERSION: ClassVar[str] = "manse-v1"
    RULE_VERSION: ClassVar[str] = "rules-v2"
    REPORT_SCHEMA_VERSION: ClassVar[str] = "report-v1"

    database_url: str
    mcp_key: SecretStr
    public_host: str
    # Direct app port stays on loopback; only the TLS proxy is public.
    bind_host: str = "127.0.0.1"
    port: int = 8080
    # Trust X-Forwarded-* only from the local TLS proxy (client scheme/address in the app).
    proxy_headers: bool = True
    forwarded_allow_ips: str = "127.0.0.1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
