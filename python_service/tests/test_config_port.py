"""Tests for the distributed C/S server port configuration."""
from server.config import Settings, settings


def test_distributed_server_default_port_is_8091():
    assert settings.PORT == 8091


def test_port_overridable_by_env(monkeypatch):
    # The field default is computed at import, but pydantic-settings re-reads
    # os.environ at each instantiation — so a fresh Settings() honors an env
    # override. This guards against a regression that hardcodes PORT and drops
    # the env-var path entirely.
    monkeypatch.setenv("PORT", "8099")
    assert Settings().PORT == 8099


def test_settings_ignores_unknown_env_file_keys(tmp_path, monkeypatch):
    # The distributed server shares the repo-root ``.env`` with the legacy
    # python_service/httpserver (dual-stack deployment). That file carries
    # httpserver-only vars (GRAPHITI_*, DB_NAME, LOG_LEVEL, ...). Unlike
    # unknown keys from os.environ (silently ignored), pydantic-settings
    # *rejects* unknown keys sourced from an ``env_file`` — so without
    # ``extra="ignore"`` the server fails to boot whenever the shared .env is
    # present. This guards that regression: Settings must tolerate the file.
    monkeypatch.delenv("PORT", raising=False)  # let the file's PORT win
    env_file = tmp_path / ".env"
    env_file.write_text(
        "PORT=8091\n"
        "GRAPHITI_USE_LOCAL_LLM=true\n"  # httpserver-only
        "DB_NAME=forensics.db\n"         # httpserver-only
        "LOG_LEVEL=INFO\n"               # httpserver-only
    )
    # Must not raise; the known key is still read from the file.
    s = Settings(_env_file=str(env_file))
    assert s.PORT == 8091
