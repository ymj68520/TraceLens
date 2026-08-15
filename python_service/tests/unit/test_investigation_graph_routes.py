"""HTTP contract tests for the C8b Investigation Graph API."""

from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import investigation
from httpserver.services.evidence import (
    EvidenceNotFoundError,
    EvidenceStoreError,
)
from httpserver.services.investigation import (
    InvestigationGraphNode,
    InvestigationGraphResponse,
)


def _response(**overrides):
    base = dict(
        task_id="A",
        base_graph_available=True,
        base_max_nodes=200,
        nodes=(
            InvestigationGraphNode(
                id="evidence:file:/case/a.txt",
                name="file:/case/a.txt",
                label="Evidence",
                source="investigation",
                confirmed=None,
                provenance={
                    "evidence_key": "file:/case/a.txt",
                    "evidence_type": "file",
                },
            ),
            InvestigationGraphNode(
                id="uuid-1",
                name="malware.exe",
                label="Entity",
                summary="s",
                source="base_kg",
            ),
        ),
        links=(),
        warnings=(),
    )
    base.update(overrides)
    return InvestigationGraphResponse(**base)


def _service_mock(**kwargs):
    service = Mock()
    service.get_graph = AsyncMock(**kwargs)
    return service


def _client(service):
    app = FastAPI()
    app.include_router(investigation.router, prefix="/api/investigation")
    app.dependency_overrides[
        investigation.get_investigation_graph_service
    ] = lambda: service
    return TestClient(app)


def test_graph_200_composition_passthrough():
    service = _service_mock(return_value=_response())
    response = _client(service).get(
        "/api/investigation/graph", params={"task_id": "A"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == "A"
    assert body["base_graph_available"] is True
    assert body["base_max_nodes"] == 200
    assert body["warnings"] == []
    assert body["nodes"][0]["id"] == "evidence:file:/case/a.txt"
    assert body["nodes"][0]["provenance"]["evidence_type"] == "file"
    assert body["nodes"][1]["source"] == "base_kg"
    service.get_graph.assert_awaited_once_with("A", max_base_nodes=200)


def test_graph_forwards_max_base_nodes():
    service = _service_mock(return_value=_response())
    response = _client(service).get(
        "/api/investigation/graph",
        params={"task_id": "A", "max_base_nodes": 300},
    )
    assert response.status_code == 200
    service.get_graph.assert_awaited_once_with("A", max_base_nodes=300)


def test_graph_degraded_mode_body():
    service = _service_mock(return_value=_response(
        base_graph_available=False,
        nodes=(),
        warnings=("base_graph_unavailable",),
    ))
    response = _client(service).get(
        "/api/investigation/graph", params={"task_id": "A"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["base_graph_available"] is False
    assert body["warnings"] == ["base_graph_unavailable"]
    assert body["nodes"] == []


def test_graph_404_task_not_found():
    service = _service_mock(side_effect=EvidenceNotFoundError("task not found"))
    response = _client(service).get(
        "/api/investigation/graph", params={"task_id": "missing"}
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "task not found"


def test_graph_503_store_unavailable():
    service = _service_mock(side_effect=EvidenceStoreError("corrupt"))
    response = _client(service).get(
        "/api/investigation/graph", params={"task_id": "A"}
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "investigation store is unavailable"


def test_graph_422_validation():
    service = _service_mock(return_value=_response())
    client = _client(service)
    for params in (
        {},
        {"task_id": ""},
        {"task_id": "A", "max_base_nodes": 0},
        {"task_id": "A", "max_base_nodes": 1001},
        {"task_id": "A", "max_base_nodes": "many"},
    ):
        response = client.get("/api/investigation/graph", params=params)
        assert response.status_code == 422, params
    service.get_graph.assert_not_awaited()
