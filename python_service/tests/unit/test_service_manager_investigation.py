"""Tests for ServiceManager C3 Investigation service wiring."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from httpserver.services.service_manager import ServiceManager
from httpserver.services.investigation import SecondaryAnalysisExecutor


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


def test_review_service_lazy_cached_and_rebinds_after_clear():
    manager, backend_a = _manager_with_backend()
    first = manager.investigation_review_service
    second = manager.investigation_review_service
    assert first is second
    assert first._cpp_backend is backend_a

    manager._clear_services()
    backend_b = object()
    manager._cpp_backend = backend_b
    manager._cpp_backend_ready = True
    manager._lifecycle_state = "running"
    replacement = manager.investigation_review_service
    assert replacement is not first
    assert replacement._cpp_backend is backend_b


def test_secondary_executor_factory_reuses_capture_during_initialization():
    manager, backend = _manager_with_backend()
    manager._lifecycle_state = "initializing"
    executor = manager._create_secondary_analysis_executor()
    assert isinstance(executor, SecondaryAnalysisExecutor)
    assert executor._cpp_backend is backend
    assert executor._capture_service is manager._investigation_service


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


def test_event_service_lazy_cached_and_rebinds_after_clear():
    manager, backend_a = _manager_with_backend()
    first = manager.investigation_event_service
    second = manager.investigation_event_service
    assert first is second
    assert first._cpp_backend is backend_a
    assert first._capture_service is manager._investigation_service

    manager._clear_services()
    backend_b = object()
    manager._cpp_backend = backend_b
    manager._cpp_backend_ready = True
    manager._lifecycle_state = "running"
    replacement = manager.investigation_event_service
    assert replacement is not first
    assert replacement._cpp_backend is backend_b
    assert replacement._capture_service is manager._investigation_service


@pytest.mark.parametrize("state", ["initializing", "shutting_down", "stopped"])
def test_event_service_respects_lifecycle_access(state):
    manager, _ = _manager_with_backend()
    manager._lifecycle_state = state
    with pytest.raises(RuntimeError):
        _ = manager.investigation_event_service


@pytest.mark.parametrize("state", ["initializing", "shutting_down", "stopped"])
def test_review_service_respects_lifecycle_access(state):
    manager, _ = _manager_with_backend()
    manager._lifecycle_state = state
    with pytest.raises(RuntimeError):
        _ = manager.investigation_review_service


def test_graph_service_lazy_cached_and_rebinds_after_clear():
    manager, backend_a = _manager_with_backend()
    first = manager.investigation_graph_service
    second = manager.investigation_graph_service
    assert first is second
    assert first._cpp_backend is backend_a

    manager._clear_services()
    backend_b = object()
    manager._cpp_backend = backend_b
    manager._cpp_backend_ready = True
    manager._lifecycle_state = "running"
    replacement = manager.investigation_graph_service
    assert replacement is not first
    assert replacement._cpp_backend is backend_b


def test_graph_service_base_provider_resolves_graphiti_lazily():
    manager, _ = _manager_with_backend()
    service = manager.investigation_graph_service

    # The provider must not have forced GraphitiService construction yet.
    assert manager._graphiti_service is None

    class _FakeGraphiti:
        async def get_graph_data(self, task_id, max_nodes):
            return [], []

    manager._graphiti_service = _FakeGraphiti()
    assert service._base_graph_provider() is manager._graphiti_service


def test_graph_service_rejects_backend_not_ready():
    manager, _ = _manager_with_backend(ready=False)
    with pytest.raises(RuntimeError, match=r"C\+\+ backend is not initialized"):
        _ = manager.investigation_graph_service


@pytest.mark.parametrize("state", ["initializing", "shutting_down", "stopped"])
def test_graph_service_respects_lifecycle_access(state):
    manager, _ = _manager_with_backend()
    manager._lifecycle_state = state
    with pytest.raises(RuntimeError):
        _ = manager.investigation_graph_service


def test_read_service_lazy_cached_and_rebinds_after_clear():
    manager, backend_a = _manager_with_backend()
    first = manager.investigation_read_service
    second = manager.investigation_read_service
    assert first is second
    assert first._cpp_backend is backend_a

    manager._clear_services()
    backend_b = object()
    manager._cpp_backend = backend_b
    manager._cpp_backend_ready = True
    manager._lifecycle_state = "running"
    replacement = manager.investigation_read_service
    assert replacement is not first
    assert replacement._cpp_backend is backend_b


def test_read_service_rejects_backend_not_ready():
    manager, _ = _manager_with_backend(ready=False)
    with pytest.raises(RuntimeError, match=r"C\+\+ backend is not initialized"):
        _ = manager.investigation_read_service


@pytest.mark.parametrize("state", ["initializing", "shutting_down", "stopped"])
def test_read_service_respects_lifecycle_access(state):
    manager, _ = _manager_with_backend()
    manager._lifecycle_state = state
    with pytest.raises(RuntimeError):
        _ = manager.investigation_read_service
