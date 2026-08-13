"""Tests for ServiceManager C3 Investigation service wiring."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from httpserver.services.service_manager import ServiceManager


def _manager_with_backend(ready=True):
    manager = ServiceManager(settings=SimpleNamespace())
    backend = object()
    manager._cpp_backend = backend
    manager._cpp_backend_ready = ready
    manager._lifecycle_state = "running"
    return manager, backend


def test_investigation_service_lazy_cached_and_binds_ready_backend():
    manager, backend = _manager_with_backend()

    first = manager.investigation_service
    second = manager.investigation_service

    assert first is second
    assert first._cpp_backend is backend
    assert first._evidence_resolver._cpp_backend is backend


def test_investigation_service_rejects_backend_not_ready():
    manager, _ = _manager_with_backend(ready=False)
    with pytest.raises(RuntimeError, match=r"C\+\+ backend is not initialized"):
        _ = manager.investigation_service


def test_investigation_service_rejects_missing_backend():
    manager = ServiceManager(settings=SimpleNamespace())
    manager._lifecycle_state = "running"
    manager._cpp_backend_ready = True
    with pytest.raises(RuntimeError, match=r"C\+\+ backend is not initialized"):
        _ = manager.investigation_service


@pytest.mark.parametrize("state", ["initializing", "shutting_down", "stopped"])
def test_investigation_service_respects_lifecycle_access(state):
    manager, _ = _manager_with_backend()
    manager._lifecycle_state = state
    with pytest.raises(RuntimeError):
        _ = manager.investigation_service


def test_clear_services_drops_old_investigation_backend_binding():
    manager, backend_a = _manager_with_backend()
    service_a = manager.investigation_service
    manager._clear_services()

    backend_b = object()
    manager._cpp_backend = backend_b
    manager._cpp_backend_ready = True
    manager._lifecycle_state = "running"
    service_b = manager.investigation_service

    assert service_b is not service_a
    assert service_b._cpp_backend is backend_b
    assert service_b._evidence_resolver._cpp_backend is backend_b
