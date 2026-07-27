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
