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


@lru_cache()
def get_data_root() -> Path:
    """Return the absolute runtime data root used by all Python services."""
    configured = Path(get_settings().data_dir).expanduser()
    if configured.is_absolute():
        return configured
    return get_project_root() / configured


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

    # Startup/recovery budgets are intentionally separate from inference timeout.
    cpp_startup_request_timeout: float = Field(default=5.0, alias="CPP_STARTUP_REQUEST_TIMEOUT")
    cpp_recovery_timeout: float = Field(default=8.0, alias="CPP_RECOVERY_TIMEOUT")
    neo4j_connect_timeout: float = Field(default=5.0, alias="NEO4J_CONNECT_TIMEOUT")
    neo4j_query_timeout: float = Field(default=5.0, alias="NEO4J_QUERY_TIMEOUT")
    optional_service_init_timeout: float = Field(default=12.0, alias="OPTIONAL_SERVICE_INIT_TIMEOUT")
    startup_timeout: float = Field(default=30.0, alias="PYTHON_STARTUP_TIMEOUT")

    # LLM Settings
    llm_base_url: str = Field(default="http://192.168.31.170:1234", alias="LLM_BASE_URL")
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
    
    llm_text_base_url: str = Field(default="http://192.168.31.170:1234", alias="LLM_TEXT_BASE_URL")
    llm_text_model: str = Field(default="openai/gpt-oss-20b", alias="LLM_TEXT_MODEL")
    llm_text_max_tokens: int = Field(default=4096, alias="LLM_TEXT_MAX_TOKENS")
    llm_text_temperature: float = Field(default=0.7, alias="LLM_TEXT_TEMPERATURE")
    
    llm_vision_base_url: str = Field(default="http://192.168.31.170:1234", alias="LLM_VISION_BASE_URL")
    llm_vision_model: str = Field(default="qwen/qwen3-vl-4b", alias="LLM_VISION_MODEL")
    llm_vision_max_tokens: int = Field(default=4096, alias="LLM_VISION_MAX_TOKENS")
    llm_vision_temperature: float = Field(default=0.5, alias="LLM_VISION_TEMPERATURE")
    
    llm_timeout_seconds: int = Field(default=120, alias="LLM_TIMEOUT_SECONDS")
    llm_max_retries: int = Field(default=3, alias="LLM_MAX_RETRIES")
    llm_context_length: int = Field(default=4096, alias="LLM_CONTEXT_LENGTH")
    # Concurrent LLM calls per analysis pipeline (event clusters, files, artifacts).
    llm_max_concurrency: int = Field(default=3, ge=1, le=64, alias="LLM_MAX_CONCURRENCY")

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

    # llm-throughput-hardening SPEC A: pause episode ingestion while a
    # pipeline analysis (LLM_ANALYSIS / PLATFORM_ANALYSIS) is using the LLM
    # server, and cap runaway jobs with a time budget (0 disables the cap).
    graphiti_foreground_gate: bool = Field(default=True, alias="GRAPHITI_FOREGROUND_GATE")
    graphiti_gate_poll_seconds: int = Field(default=30, ge=1, le=600, alias="GRAPHITI_GATE_POLL_SECONDS")
    graphiti_job_timeout_hours: int = Field(default=12, ge=0, le=168, alias="GRAPHITI_JOB_TIMEOUT_HOURS")
    # mvp-phase1-acceptance SPEC §3: ingestion model pinned to phi-4; the env
    # var may override, empty/unset falls back to the pin (never LLM_TEXT_MODEL).
    graphiti_llm_model: str = Field(default="microsoft/phi-4", alias="GRAPHITI_LLM_MODEL")

    # mvp-phase1-acceptance SPEC §4: MVP scope switches. Defaults are the
    # acceptance form; set the env var to "true" to restore full behaviour.
    event_llm_analysis_enabled: bool = Field(default=False, alias="EVENT_LLM_ANALYSIS_ENABLED")
    combined_case_enabled: bool = Field(default=False, alias="COMBINED_CASE_ENABLED")
    workbench_llm_enabled: bool = Field(default=False, alias="WORKBENCH_LLM_ENABLED")
    # SPEC §4.6/§4.7 (2026-09-18 second trim): memory forensics and OSS
    # analysis are cut from the phase-1 acceptance scope entirely.
    memory_forensics_enabled: bool = Field(default=False, alias="MEMORY_FORENSICS_ENABLED")
    oss_analysis_enabled: bool = Field(default=False, alias="OSS_ANALYSIS_ENABLED")
    
    # Database Settings
    db_output_dir: str = Field(default="./output", alias="DB_OUTPUT_DIR")
    db_name: str = Field(default="forensics.db", alias="DB_NAME")

    report_output_dir: str = Field(
        default="build/data/reports", alias="FORENSIC_REPORT_DIR"
    )
    report_generator_version: str = Field(
        default="1.0.0", alias="FORENSIC_REPORT_GENERATOR_VERSION"
    )

    # Finite analysis limits. Explicit values may raise these within the
    # declared bounds; an omitted value never means unlimited.
    llm_max_files: int = Field(default=500, ge=1, le=100000, alias="LLM_MAX_FILES")
    llm_smart_candidate_files: int = Field(default=1000, ge=1, le=100000, alias="LLM_SMART_CANDIDATE_FILES")
    # Event-cluster analysis budget (SPEC event-cluster-analysis-redesign §5):
    # the maximum number of clusters one analysis run may produce. Phase C
    # adaptive bucketing targets this value; deployments raise it via config
    # (e.g. LLM_MAX_EVENT_CLUSTERS=1500) at the cost of LLM calls.
    llm_max_event_clusters: int = Field(default=200, ge=1, le=100000, alias="LLM_MAX_EVENT_CLUSTERS")
    # Map-reduce chunk size for event-cluster analysis: events per LLM call.
    # Every event enters at least one chunk — no sampling (SPEC §6).
    cluster_analysis_chunk_size: int = Field(default=200, ge=1, le=10000, alias="CLUSTER_ANALYSIS_CHUNK_SIZE")
    llm_max_artifacts: int = Field(default=500, ge=1, le=100000, alias="LLM_MAX_ARTIFACTS")
    investigation_max_nodes: int = Field(default=200, ge=1, le=10000, alias="INVESTIGATION_MAX_NODES")
    multi_image_max_filter_files: int = Field(default=400, ge=1, le=20000, alias="MULTI_IMAGE_MAX_FILTER_FILES")

    # File Analysis Settings
    file_analysis_max_content: int = Field(default=10000, ge=1, le=1000000, alias="FILE_ANALYSIS_MAX_CONTENT")
    file_analysis_max_keywords: int = Field(default=10, ge=1, le=1000, alias="FILE_ANALYSIS_MAX_KEYWORDS")
    file_analysis_max_content_limit: int = Field(default=50000, ge=1, le=1000000, alias="FILE_ANALYSIS_MAX_CONTENT_LIMIT")
    
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


def mask_url_credentials(url: str) -> str:
    """Return ``url`` with any password component masked."""
    from urllib.parse import urlsplit, urlunsplit

    try:
        parts = urlsplit(url)
    except ValueError:
        return "***"
    if parts.password is None:
        return url
    userinfo = f"{parts.username}:***" if parts.username is not None else ":***"
    hostinfo = parts.hostname or ""
    if parts.port is not None:
        hostinfo = f"{hostinfo}:{parts.port}"
    return urlunsplit(
        (parts.scheme, f"{userinfo}@{hostinfo}", parts.path, parts.query, parts.fragment)
    )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Module-level settings access
settings = get_settings()
