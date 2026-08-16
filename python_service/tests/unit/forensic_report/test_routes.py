"""HTTP contract tests for versioned forensic report snapshots."""

import importlib
import sqlite3
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.routing import Match

from httpserver.routes import forensic_reports
from httpserver.services.forensic_report.service import ReportServiceUnavailable
from httpserver.services.forensic_report.models import ReportVersion, ScopeType, SearchHit


ROOT = Path(__file__).resolve().parents[3]


def version(**overrides: Any) -> ReportVersion:
    values = {
        "report_id": "r1",
        "version": 1,
        "scope_type": ScopeType.TASK,
        "scope_id": "t1",
        "status": "queued",
        "title": "Task report",
        "task_ids": ["t1"],
        "stage": "queued",
        "progress": 0,
        "warnings": [],
    }
    values.update(overrides)
    return ReportVersion.model_validate(values)


class FakeReportService:
    def __init__(self) -> None:
        self.started: list[tuple[ScopeType, str]] = []
        self.versions: list[ReportVersion] = []
        self.status: ReportVersion | None = version()
        self.manifest_path: Path | Exception | None = None
        self.page_path: Path | Exception | None = None
        self.search_result: tuple[int, list[Any]] | Exception = (0, [])

    async def start(self, scope_type: ScopeType, scope_id: str) -> ReportVersion:
        self.started.append((scope_type, scope_id))
        return version(scope_type=scope_type, scope_id=scope_id)

    def list_versions(self, scope_type: ScopeType, scope_id: str) -> list[ReportVersion]:
        return self.versions

    def get_status(self, report_id: str) -> ReportVersion | None:
        return self.status

    def get_manifest_path(self, report_id: str) -> Path:
        return self._return_or_raise(self.manifest_path)

    def get_page_path(self, report_id: str, category_id: str, page: int) -> Path:
        return self._return_or_raise(self.page_path)

    def search(self, report_id: str, query: str, offset: int, limit: int) -> tuple[int, list[Any]]:
        return self._return_or_raise(self.search_result)

    @staticmethod
    def _return_or_raise(value: Any) -> Any:
        if isinstance(value, Exception):
            raise value
        return value


def make_client(service: FakeReportService) -> TestClient:
    app = FastAPI()
    app.include_router(forensic_reports.router, prefix="/api/reports")
    app.dependency_overrides[forensic_reports.get_report_service] = lambda: service
    return TestClient(app)


def test_report_dependency_sanitizes_service_lifecycle_errors(monkeypatch) -> None:
    class UnavailableManager:
        @property
        def forensic_report_service(self):
            raise RuntimeError("ServiceManager is shutting_down at /private/reports")

    monkeypatch.setattr(forensic_reports, "get_service_manager", lambda: UnavailableManager())
    app = FastAPI()
    app.include_router(forensic_reports.router, prefix="/api/reports")

    response = TestClient(app).get("/api/reports?scope_type=task&scope_id=t1")

    assert response.status_code == 503
    assert response.json()["detail"] == "report service is unavailable"
    assert "shutting_down" not in response.text
    assert "/private" not in response.text


def test_create_and_list_report_versions() -> None:
    service = FakeReportService()
    client = make_client(service)

    created = client.post("/api/reports", json={"scope_type": "task", "scope_id": "t1"})
    listed = client.get("/api/reports?scope_type=task&scope_id=t1")

    assert created.status_code == 202
    assert created.json()["report_id"] == "r1"
    assert service.started == [(ScopeType.TASK, "t1")]
    assert listed.status_code == 200
    assert listed.json() == []


def test_create_maps_shutdown_start_rejection_to_sanitized_service_unavailable() -> None:
    service = FakeReportService()

    async def reject_start(scope_type: ScopeType, scope_id: str) -> ReportVersion:
        raise ReportServiceUnavailable("report service is not accepting new starts")

    service.start = reject_start  # type: ignore[method-assign]
    response = make_client(service).post(
        "/api/reports", json={"scope_type": "task", "scope_id": "t1"}
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "report service is unavailable"
    assert "accepting" not in response.text


def test_create_maps_unknown_scope_and_unsupported_generation_without_details() -> None:
    service = FakeReportService()

    async def missing_scope(scope_type: ScopeType, scope_id: str) -> ReportVersion:
        raise LookupError("task /private/tasks/t1 is missing")

    service.start = missing_scope  # type: ignore[method-assign]
    response = make_client(service).post(
        "/api/reports", json={"scope_type": "task", "scope_id": "t1"}
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "report scope not found"
    assert "/private" not in response.text

    async def unsupported(scope_type: ScopeType, scope_id: str) -> ReportVersion:
        raise NotImplementedError("case report generation is not implemented")

    service.start = unsupported  # type: ignore[method-assign]
    response = make_client(service).post(
        "/api/reports", json={"scope_type": "case", "scope_id": "c1"}
    )
    assert response.status_code == 501
    assert response.json()["detail"] == "report scope type is not supported"


def test_report_request_parameters_require_valid_scope_and_bounds() -> None:
    client = make_client(FakeReportService())

    assert client.post("/api/reports", json={"scope_type": "task", "scope_id": ""}).status_code == 422
    assert client.get("/api/reports?scope_type=invalid&scope_id=t1").status_code == 422
    assert client.get("/api/reports?scope_type=task&scope_id=").status_code == 422
    assert client.get("/api/reports/r1/categories/c1/pages/0").status_code == 422
    assert client.get("/api/reports/r1/search?q=&offset=0&limit=1").status_code == 422
    assert client.get("/api/reports/r1/search?q=x&offset=-1&limit=1").status_code == 422
    assert client.get("/api/reports/r1/search?q=x&offset=0&limit=201").status_code == 422


def test_status_and_manifest_distinguish_unknown_not_ready_and_integrity_errors(tmp_path: Path) -> None:
    service = FakeReportService()
    client = make_client(service)

    service.status = None
    assert client.get("/api/reports/missing/status").status_code == 404

    service.manifest_path = KeyError("r1")
    assert client.get("/api/reports/missing/manifest").status_code == 404

    service.manifest_path = RuntimeError("report is not ready: generating")
    assert client.get("/api/reports/r1/manifest").status_code == 409

    service.manifest_path = ValueError("report path must remain confined to /private/report-root")
    response = client.get("/api/reports/r1/manifest")
    assert response.status_code == 500
    assert response.json()["detail"] == "report resource integrity error"
    assert "/private" not in response.text

    service.manifest_path = tmp_path / "missing.json"
    response = client.get("/api/reports/r1/manifest")
    assert response.status_code == 500
    assert response.json()["detail"] == "report resource integrity error"


def test_manifest_and_page_are_served_as_json_through_service_paths(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"report_id": "r1"}', encoding="utf-8")
    page = tmp_path / "page-1.json"
    page.write_text('{"records": []}', encoding="utf-8")
    service = FakeReportService()
    service.manifest_path = manifest
    service.page_path = page
    client = make_client(service)

    manifest_response = client.get("/api/reports/r1/manifest")
    page_response = client.get("/api/reports/r1/categories/android.sms/pages/1")

    assert manifest_response.status_code == 200
    assert manifest_response.headers["content-type"].startswith("application/json")
    assert manifest_response.json() == {"report_id": "r1"}
    assert page_response.status_code == 200
    assert page_response.headers["content-type"].startswith("application/json")
def test_manifest_and_page_reject_invalid_json_without_leaking_paths(tmp_path: Path) -> None:
    broken = tmp_path / "manifest.json"
    broken.write_text("{", encoding="utf-8")
    service = FakeReportService()
    service.manifest_path = broken
    service.page_path = broken
    client = make_client(service)

    manifest_response = client.get("/api/reports/r1/manifest")
    page_response = client.get("/api/reports/r1/categories/android.sms/pages/1")

    assert manifest_response.status_code == 500
    assert page_response.status_code == 500
    assert manifest_response.json()["detail"] == "report resource integrity error"
    assert page_response.json()["detail"] == "report resource integrity error"
    assert str(tmp_path) not in manifest_response.text


def test_file_response_rejects_nonstandard_json_constants_and_deep_recursion(
    tmp_path: Path,
) -> None:
    invalid_constant = tmp_path / "invalid-constant.json"
    invalid_constant.write_text('{"value": NaN}', encoding="utf-8")
    deeply_nested = tmp_path / "deeply-nested.json"
    deeply_nested.write_text("[" * 10000 + "]" * 10000, encoding="utf-8")
    service = FakeReportService()
    client = make_client(service)

    service.manifest_path = invalid_constant
    invalid_response = client.get("/api/reports/r1/manifest")
    assert invalid_response.status_code == 500
    assert invalid_response.json()["detail"] == "report resource integrity error"

    service.manifest_path = deeply_nested
    recursion_response = client.get("/api/reports/r1/manifest")
    assert recursion_response.status_code == 500
    assert recursion_response.json()["detail"] == "report resource integrity error"


def test_search_corrupt_index_returns_generic_error_without_changing_file(tmp_path: Path) -> None:
    index = tmp_path / "search.sqlite3"
    index.write_bytes(b"not a sqlite database")
    before = index.read_bytes()
    service = FakeReportService()
    service.search_result = sqlite3.DatabaseError(f"file is not a database: {index}")

    response = make_client(service).get("/api/reports/r1/search?q=x")

    assert response.status_code == 500
    assert response.json()["detail"] == "report search index is unavailable"
    assert str(index) not in response.text
    assert index.read_bytes() == before


def test_search_serializes_model_and_mapping_hits_and_stabilizes_integrity_failures() -> None:
    service = FakeReportService()
    service.search_result = (
        2,
        [
            SearchHit(kind="record", title="短信", snippet="验证码", matched_field="search_text"),
            {"kind": "record", "title": "Call", "snippet": "13800138000", "matched_field": "search_text"},
        ],
    )
    client = make_client(service)

    response = client.get("/api/reports/r1/search?q=验证码&offset=0&limit=50")
    assert response.status_code == 200
    assert response.json() == {
        "total": 2,
        "offset": 0,
        "limit": 50,
        "hits": [
            {
                "record_id": None,
                "kind": "record",
                "title": "短信",
                "snippet": "验证码",
                "matched_field": "search_text",
                "evidence_id": None,
                "platform": None,
                "category_id": None,
                "page": None,
            },
            {"kind": "record", "title": "Call", "snippet": "13800138000", "matched_field": "search_text"},
        ],
    }

    service.search_result = FileNotFoundError("/private/snapshots/r1/search.sqlite3")
    response = client.get("/api/reports/r1/search?q=x")
    assert response.status_code == 500
    assert response.json()["detail"] == "report search index is unavailable"
    assert "/private" not in response.text

    service.search_result = ValueError("report path must remain confined to /private")
    response = client.get("/api/reports/r1/search?q=x")
    assert response.status_code == 500
    assert response.json()["detail"] == "report search index is unavailable"
    assert "/private" not in response.text




def _assert_one_effective_route(app: FastAPI, method: str, path: str) -> None:
    scope = {"type": "http", "method": method, "path": path, "headers": []}
    matches = sum(
        route.matches(scope.copy())[0] is Match.FULL for route in app.routes
    )
    assert matches == 1, f"expected one full route match for {method} {path}, got {matches}"


def test_effective_route_cardinality_rejects_deliberate_duplicate_registration() -> None:
    app = FastAPI()
    app.include_router(forensic_reports.router, prefix="/api/reports")
    app.include_router(forensic_reports.router, prefix="/api/reports")

    with pytest.raises(AssertionError, match="expected one full route match"):
        _assert_one_effective_route(app, "GET", "/api/reports/r1/manifest")


def test_application_registration_exposes_report_routes_and_preserves_legacy_routes(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=lambda *args, **kwargs: None))
    monkeypatch.setitem(sys.modules, "multipart", MagicMock(__version__="0.0.1"))
    monkeypatch.setitem(sys.modules, "multipart.multipart", MagicMock(parse_options_header=object()))
    sys.modules.pop("httpserver.main", None)
    main = importlib.import_module("httpserver.main")
    app = FastAPI()

    main._register_routes(app)

    expected_report_routes = {
        ("/api/reports", "post"),
        ("/api/reports", "get"),
        ("/api/reports/evidence", "post"),
        ("/api/reports/evidence", "get"),
        ("/api/reports/evidence", "put"),
        ("/api/reports/{report_id}/status", "get"),
        ("/api/reports/{report_id}/manifest", "get"),
        ("/api/reports/{report_id}/categories/{category_id}/pages/{page}", "get"),
        ("/api/reports/{report_id}/search", "get"),
    }
    effective_paths = app.openapi()["paths"]
    effective_routes = {
        (path, method)
        for path, operations in effective_paths.items()
        for method in operations
        if method in {"get", "post", "put", "patch", "delete", "options", "head"}
    }

    assert expected_report_routes <= effective_routes
    assert {
        (path, method)
        for path, method in effective_routes
        if path.startswith("/api/reports")
    } == expected_report_routes
    assert ("/api/llm/cases", "get") in effective_routes
    assert ("/api/llm/analyze/dll", "post") in effective_routes

    for method, path in (
        ("POST", "/api/reports"),
        ("GET", "/api/reports"),
        ("GET", "/api/reports/r1/status"),
        ("GET", "/api/reports/r1/manifest"),
        ("GET", "/api/reports/r1/categories/c1/pages/1"),
        ("GET", "/api/reports/r1/search"),
        ("GET", "/api/llm/cases"),
        ("POST", "/api/llm/analyze/dll"),
    ):
        _assert_one_effective_route(app, method, path)


def test_vite_proxy_routes_reports_before_broad_api() -> None:
    vite_source = (ROOT.parent / "web" / "vite.config.js").read_text(encoding="utf-8")
    assert vite_source.index("'/api/reports'") < vite_source.index("'/api'")
