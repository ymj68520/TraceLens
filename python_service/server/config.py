"""
Application configuration.

Centralizes all runtime settings behind a single :class:`Settings` instance
loaded from environment variables / a local ``.env`` file via
`pydantic-settings <https://docs.pydantic.dev/latest/concepts/pydantic_settings/>`_.

Every module that needs configuration imports the module-level :data:`settings`
singleton rather than reading ``os.getenv`` directly, so the source of truth
stays in one place. Defaults are tuned for local development; production
deployments override values through environment variables.
"""
import os
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings.

    Values are populated in this order (later overrides earlier):
    constructor kwargs > environment variables > ``.env`` file > field defaults.
    Field names are case-sensitive and must match the env var exactly.
    """

    # Application
    APP_NAME: str = "TraceLens Server"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    # Server (distributed C/S backend).
    # Port 8091, NOT 8090: the legacy python_service/httpserver (LLM/graphiti
    # proxy for the local-mode C++ 8080 server) already owns 8090. Dual-stack
    # deployments run both simultaneously; see the port map in
    # docs/superpowers/plans/2026-07-27-cs-integration-hardening.md.
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8091"))

    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/tracelens",
    )

    # JWT
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "change-this-in-production")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    USER_TOKEN_EXPIRE_HOURS: int = 1
    CLIENT_TOKEN_EXPIRE_DAYS: int = 30

    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ]

    # File Upload
    MAX_UPLOAD_SIZE: int = 5 * 1024 * 1024 * 1024  # 5GB
    MAX_LLM_TEXT_SIZE: int = 10 * 1024 * 1024  # 10MB

    # Command Queue
    DEFAULT_POLL_INTERVAL: int = 10  # seconds
    MIN_POLL_INTERVAL: int = 5
    MAX_POLL_INTERVAL: int = 30
    DEFAULT_COMMAND_TTL_HOURS: int = 24
    CRITICAL_COMMAND_TTL_HOURS: int = 1

    # Organization
    DEFAULT_ORGANIZATION_NAME: str = "Default Organization"
    DEFAULT_SUBSCRIPTION_TIER: str = "enterprise"

    # extra="ignore": the distributed server shares the repo-root ``.env``
    # with the legacy python_service/httpserver (dual-stack deployment). That
    # file carries httpserver-only vars (GRAPHITI_*, DB_NAME, LOG_LEVEL, ...);
    # pydantic-settings rejects unknown keys sourced from an ``env_file``
    # (unlike keys from os.environ, which it silently ignores), so without
    # this the server fails to boot whenever the shared .env is present.
    # Mirror httpserver/config.py's own extra="ignore".
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")


settings = Settings()
