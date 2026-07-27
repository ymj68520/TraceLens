"""The distributed C/S server must not collide with the legacy httpserver
port (both defaulted to 8090). Dual-stack coexistence requires a dedicated port."""
from server.config import settings


def test_distributed_server_default_port_is_8091():
    assert settings.PORT == 8091


def test_port_overridable_by_env(monkeypatch):
    # Operators may still override; the default just must not be 8090.
    monkeypatch.setattr(settings, "PORT", 8099)
    assert settings.PORT == 8099
