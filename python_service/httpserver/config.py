"""
Configuration management for the HTTP server.

Loads settings from environment variables and .env file.
Uses pydantic-settings for validation and type safety.
"""

import os
import json
from functools import lru_cache
from pathlib import Path
from typing import Optional, List, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def find_env_file() -> Optional[Path]:
    """Find .env file by searching from current directory up to project root."""
    current = Path.cwd()
    while current != current.parent:
        env_path = current / ".env"
        if env_path.exists():
            return env_path
        current = current.parent
    return None


@lru_cache()
def get_project_root() -> Path:
    """Resolve project root: .env PROJECT_ROOT first, auto-detect fallback."""
    settings = get_settings()
    if settings.project_root:
        root = Path(settings.project_root)
        if root.is_dir():
            return root
    # Auto-detect: config.py -> httpserver -> python_service -> project_root
    return Path(__file__).resolve().parents[2]


class LLMFilterConfig(BaseModel):
    """Configuration for LLM file filtering enhancements."""

    # Parser settings
    enable_enhanced_parser: bool = Field(
        default=True,
        description="Enable enhanced LLM response parser"
    )
    parser_fallback_enabled: bool = Field(
        default=True,
        description="Enable fallback to legacy parser on failure"
    )

    # Matcher settings
    match_confidence_threshold: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for matches"
    )
    enable_smart_dedup: bool = Field(
        default=True,
        description="Enable smart duplicate file resolution"
    )

    # Scoring weights (must sum to 1.0)
    score_weight_path_semantic: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="Weight for path semantic relevance scoring"
    )
    score_weight_freshness: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Weight for file freshness scoring"
    )
    score_weight_size: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Weight for file size scoring"
    )
    score_weight_depth: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="Weight for path depth scoring"
    )

    # Concurrent control
    enable_concurrent_lock: bool = Field(
        default=True,
        description="Enable task-level concurrent filtering lock"
    )
    lock_timeout: int = Field(
        default=300,
        ge=1,
        le=3600,
        description="Lock acquisition timeout in seconds"
    )

    # Retry settings
    max_parse_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Maximum parsing retry attempts"
    )
    retry_delay: int = Field(
        default=1,
        ge=0,
        le=10,
        description="Base delay between retries in seconds"
    )

    class Config:
        validate_assignment = True


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=find_env_file(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Server Settings
    python_http_port: int = Field(default=8090, alias="PYTHON_HTTP_PORT")
    python_http_host: str = Field(default="0.0.0.0", alias="PYTHON_HTTP_HOST")
    
    # Project Path Settings
    project_root: str = Field(default="", alias="PROJECT_ROOT")
    data_dir: str = Field(default="data", alias="DATA_DIR")
    
    # C++ Backend Settings
    cpp_backend_url: str = Field(default="http://localhost:8080", alias="CPP_BACKEND_URL")
    http_server_port: int = Field(default=8080, alias="HTTP_SERVER_PORT")
    http_server_host: str = Field(default="0.0.0.0", alias="HTTP_SERVER_HOST")

    # DLL Analysis Settings
    dll_analysis_enabled: bool = Field(default=True, env="DLL_ANALYSIS_ENABLED")
    dll_cpp_backend_url: str = Field(default="http://localhost:8080", env="DLL_CPP_BACKEND_URL")
    dll_analysis_timeout: float = Field(default=30.0, env="DLL_ANALYSIS_TIMEOUT")

    # LLM Settings
    llm_base_url: str = Field(default="http://localhost:1234", alias="LLM_BASE_URL")
    llm_endpoint: str = Field(default="/v1/chat/completions", alias="LLM_ENDPOINT")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")

    @field_validator("llm_endpoint", mode="before")
    @classmethod
    def normalize_llm_endpoint(cls, value: str) -> str:
        """Keep legacy model-name values from becoming request URL paths."""
        endpoint = str(value or "").strip()
        if not endpoint or endpoint.split("/", 1)[0] not in {"http:", "https:"} and not endpoint.startswith("/"):
            return "/v1/chat/completions"
        return endpoint
    
    llm_text_base_url: str = Field(default="http://localhost:1234", alias="LLM_TEXT_BASE_URL")
    llm_text_model: str = Field(default="openai/gpt-oss-20b", alias="LLM_TEXT_MODEL")
    llm_text_max_tokens: int = Field(default=4096, alias="LLM_TEXT_MAX_TOKENS")
    llm_text_temperature: float = Field(default=0.7, alias="LLM_TEXT_TEMPERATURE")
    
    llm_vision_base_url: str = Field(default="http://localhost:1234", alias="LLM_VISION_BASE_URL")
    llm_vision_model: str = Field(default="qwen/qwen3-vl-4b", alias="LLM_VISION_MODEL")
    llm_vision_max_tokens: int = Field(default=4096, alias="LLM_VISION_MAX_TOKENS")
    llm_vision_temperature: float = Field(default=0.5, alias="LLM_VISION_TEMPERATURE")
    
    llm_timeout_seconds: int = Field(default=120, alias="LLM_TIMEOUT_SECONDS")
    llm_max_retries: int = Field(default=3, alias="LLM_MAX_RETRIES")
    llm_context_length: int = Field(default=4096, alias="LLM_CONTEXT_LENGTH")

    # Redis Settings (optional; IngestionJobManager falls back to in-memory)
    redis_url: str = Field(default="redis://localhost:6379", alias="REDIS_URL")

    # OSS Settings
    oss_access_key_id: str = Field(default="", alias="OSS_ACCESS_KEY_ID")
    oss_access_key_secret: str = Field(default="", alias="OSS_ACCESS_KEY_SECRET")
    oss_endpoint: str = Field(default="", alias="OSS_ENDPOINT")
    oss_region: str = Field(default="cn-hangzhou", alias="OSS_REGION")

    # Neo4j / Graphiti Settings
    neo4j_uri: str = Field(default="neo4j://127.0.0.1:7687", alias="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", alias="NEO4J_USER")
    neo4j_password: str = Field(default="", alias="NEO4J_PASSWORD")
    
    graphiti_use_local_llm: bool = Field(default=True, alias="GRAPHITI_USE_LOCAL_LLM")
    graphiti_batch_size: int = Field(default=50, alias="GRAPHITI_BATCH_SIZE")
    graphiti_max_retries: int = Field(default=3, alias="GRAPHITI_MAX_RETRIES")
    graphiti_group_id: str = Field(default="forensics_files", alias="GRAPHITI_GROUP_ID")
    # Whether to include the full llm_description in each episode body. More text
    # gives the entity-extraction LLM richer context (more entities/relations) at
    # the cost of tokens. Mirrors graphiti_integration.GraphitiConfig default.
    graphiti_include_full_desc: bool = Field(default=True, alias="GRAPHITI_INCLUDE_FULL_DESC")
    graphiti_max_episode_tokens: int = Field(default=3000, alias="GRAPHITI_MAX_EPISODE_TOKENS")
    
    # Database Settings
    db_output_dir: str = Field(default="./output", alias="DB_OUTPUT_DIR")
    db_name: str = Field(default="forensics.db", alias="DB_NAME")

    report_output_dir: str = Field(
        default="build/data/reports", alias="FORENSIC_REPORT_DIR"
    )
    report_generator_version: str = Field(
        default="1.0.0", alias="FORENSIC_REPORT_GENERATOR_VERSION"
    )

    # File Analysis Settings
    file_analysis_max_content: int = Field(default=10000, alias="FILE_ANALYSIS_MAX_CONTENT")
    file_analysis_max_keywords: int = Field(default=10, alias="FILE_ANALYSIS_MAX_KEYWORDS")
    file_analysis_max_content_limit: int = Field(default=12000, alias="FILE_ANALYSIS_MAX_CONTENT_LIMIT")
    
    # Logging Settings
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_file: str = Field(default="forensics.log", alias="LOG_FILE")
    debug_output_mode: str = Field(default="stdout", alias="DEBUG_OUTPUT_MODE")
    
    # Performance Settings
    thread_pool_size: int = Field(default=4, alias="THREAD_POOL_SIZE")
    max_batch_size: int = Field(default=100, alias="MAX_BATCH_SIZE")

    # CORS Settings (stored as string, parsed via property)
    cors_origins_raw: str = Field(
        default='["*"]',
        alias="PYTHON_CORS_ORIGINS",
        description="List of allowed CORS origins in JSON array format. "
                    "Example: '[\"https://example.com\", \"https://app.example.com\"]'"
    )

    @property
    def cors_origins(self) -> List[str]:
        """Parse and return CORS origins list."""
        return self._parse_cors_origins(self.cors_origins_raw)

    @staticmethod
    def _parse_cors_origins(value: str) -> List[str]:
        """Parse CORS origins from string format.

        Supports JSON array format: '["https://example.com", "https://app.example.com"]'
        Falls back to comma-separated format for convenience.
        """
        if not value or value.strip() == "*":
            return ["*"]

        value = value.strip()

        # Try to parse as JSON first
        if value.startswith("["):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except json.JSONDecodeError:
                pass

        # Fallback to comma-separated format
        origins = [item.strip() for item in value.split(",") if item.strip()]
        return origins if origins else ["*"]


def mask_url_credentials(url: str) -> str:
    """Return ``url`` with any password component masked.

    Used whenever a service URL (redis://:pass@host, postgresql://user:pass@
    host) may reach a client response or a log line; the full value stays in
    settings only. Unparseable values degrade to a fixed string rather than
    echoing the input.
    """
    from urllib.parse import urlsplit, urlunsplit

    try:
        parts = urlsplit(url)
    except ValueError:
        return "***"
    if parts.password is None:
        return url
    userinfo = (
        f"{parts.username}:***" if parts.username is not None else ":***"
    )
    hostinfo = parts.hostname or ""
    if parts.port is not None:
        hostinfo = f"{hostinfo}:{parts.port}"
    masked = urlunsplit(
        (parts.scheme, f"{userinfo}@{hostinfo}", parts.path, parts.query, parts.fragment)
    )
    return masked

    # LLM Filter Configuration
    llm_filter_config: LLMFilterConfig = Field(
        default_factory=LLMFilterConfig,
        description="LLM file filtering configuration"
    )

    # File Filter Selection Mode
    file_filter_mode: Literal["deterministic", "llm"] = Field(
        default="deterministic",
        alias="FILE_FILTER_MODE",
        description="File selection mode: 'deterministic' (default, reuses the "
                    "C++ FileFilter product in files.db) or 'llm' (legacy LLM "
                    "selection by case_description)."
    )
    filter_max_files: int = Field(
        default=0,
        alias="FILTER_MAX_FILES",
        description="Max files selected in deterministic mode. 0 = unlimited "
                    "(select all files meeting the profile)."
    )

    @property
    def cpp_backend_base_url(self) -> str:
        """Get the full C++ backend URL."""
        return f"http://{self.http_server_host}:{self.http_server_port}"
    
    @property
    def llm_full_endpoint(self) -> str:
        """Get the full LLM endpoint URL."""
        return f"{self.llm_base_url}{self.llm_endpoint}"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Module-level settings access
settings = get_settings()
