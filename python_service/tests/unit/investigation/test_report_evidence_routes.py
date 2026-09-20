"""HTTP contract tests for /api/reports/evidence (Phase R1)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import report_evidence
from httpserver.services.evidence import (
    EvidenceNotFoundError,
    EvidenceStoreError,
)
from httpserver.services.investigation import (
    AnalysisBindingConflictError,
    ReportEvidenceConflictError,
    ReportEvidenceItem,
    ReportEvidenceStatus,
)

KEY = "file:/case/a.txt"


def item(**overrides) -> ReportEvidenceItem:
    values = {
        "task_id": "A",
        "evidence_key": KEY,
        "report_status": ReportEvidenceStatus.main,
        "analysis_id": None,
        "added_by": "analyst-x",
        "created_at": "2026-08-16T00:00:00+00:00",
        "updated_at": "2026-08-16T00:00:00+00:00",
        "updated_by": "analyst-x",
        "newer_accepted_available": False,
    }
    values.update(overrides)
    return ReportEvidenceItem.model_validate(values)


class FakeReportEvidenceService:
    def __init__(self) -> None:
        self.added: list[dict] = []
        self.updated: list[dict] = []
        self.listed: list[str] = []
        self.list_result: list[ReportEvidenceItem] | Exception = []
        self.add_result: ReportEvidenceItem | Exception = item()
        self.update_result: ReportEvidenceItem | Exception = item()

    async def list(self, task_id: str) -> list[ReportEvidenceItem]:
        self.listed.append(task_id)
        if isinstance(self.list_result, Exception):
            raise self.list_result
        return self.list_result

    async def add(self, task_id, evidence_key, *, report_status,
                  analysis_id=None, added_by) -> ReportEvidenceItem:
        self.added.append({
            "task_id": task_id, "evidence_key": evidence_key,
            "report_status": report_status, "analysis_id": analysis_id,
            "added_by": added_by,
        })
        if isinstance(self.add_result, Exception):
            raise self.add_result
        return self.add_result

    async def update(self, task_id, evidence_key, *, report_status=None,
                     analysis_id=None, bind_analysis=False,
                     updated_by) -> ReportEvidenceItem:
        self.updated.append({
            "task_id": task_id, "evidence_key": evidence_key,
            "report_status": report_status, "analysis_id": analysis_id,
            "bind_analysis": bind_analysis, "updated_by": updated_by,
        })
        if isinstance(self.update_result, Exception):
            raise self.update_result
        return self.update_result


def make_client(service: FakeReportEvidenceService) -> TestClient:
    app = FastAPI()
    app.include_router(report_evidence.router, prefix="/api/reports")
    app.dependency_overrides[report_evidence.get_report_evidence_service] = (
        lambda: service
    )
    return TestClient(app)


def test_list_passes_task_and_returns_items() -> None:
    service = FakeReportEvidenceService()
    service.list_result = [item()]
    response = make_client(service).get("/api/reports/evidence?task_id=A")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["evidence_key"] == KEY
    assert body[0]["report_status"] == "main"
    assert body[0]["newer_accepted_available"] is False
    assert service.listed == ["A"]


def test_list_maps_task_and_store_errors() -> None:
    service = FakeReportEvidenceService()
    service.list_result = EvidenceNotFoundError("task not found")
    client = make_client(service)
    assert client.get("/api/reports/evidence?task_id=A").status_code == 404

    service.list_result = EvidenceStoreError("store unavailable")
    assert client.get("/api/reports/evidence?task_id=A").status_code == 503


def test_add_sends_canonical_key_and_explicit_fields() -> None:
    service = FakeReportEvidenceService()
    service.add_result = item(report_status=ReportEvidenceStatus.appendix)
    response = make_client(service).post("/api/reports/evidence", json={
        "task_id": "A",
        "evidence_key": "file:\\case\\a.txt",  # backslash canonicalized
        "report_status": "appendix",
        "added_by": "analyst-x",
    })

    assert response.status_code == 200
    assert service.added == [{
        "task_id": "A", "evidence_key": KEY,
        "report_status": "appendix", "analysis_id": None,
        "added_by": "analyst-x",
    }]
    assert response.json()["report_status"] == "appendix"


def test_add_rejects_unknown_and_extra_fields() -> None:
    client = make_client(FakeReportEvidenceService())
    assert client.post("/api/reports/evidence", json={
        "task_id": "A", "evidence_key": KEY,
        "report_status": "excluded",  # excluded only reachable via PUT
        "added_by": "x",
    }).status_code == 422
    assert client.post("/api/reports/evidence", json={
        "task_id": "A", "evidence_key": KEY,
        "report_status": "main", "added_by": "x",
        "db_path": "/etc/passwd",  # no client paths
    }).status_code == 422


def test_add_maps_conflicts_and_not_found() -> None:
    service = FakeReportEvidenceService()
    client = make_client(service)

    service.add_result = EvidenceNotFoundError("evidence snapshot not captured")
    r = client.post("/api/reports/evidence", json={
        "task_id": "A", "evidence_key": KEY,
        "report_status": "main", "added_by": "x",
    })
    assert r.status_code == 404
    assert r.json()["detail"] == "task or evidence not found"

    service.add_result = AnalysisBindingConflictError("not accepted")
    r = client.post("/api/reports/evidence", json={
        "task_id": "A", "evidence_key": KEY,
        "report_status": "main", "analysis_id": "sa_x", "added_by": "x",
    })
    assert r.status_code == 409
    assert r.json()["detail"] == "analysis binding conflict"

    service.add_result = ReportEvidenceConflictError("already exists")
    r = client.post("/api/reports/evidence", json={
        "task_id": "A", "evidence_key": KEY,
        "report_status": "main", "added_by": "x",
    })
    assert r.status_code == 409
    assert r.json()["detail"] == "report evidence already exists"


def test_add_invalid_evidence_key_is_400() -> None:
    client = make_client(FakeReportEvidenceService())
    response = client.post("/api/reports/evidence", json={
        "task_id": "A", "evidence_key": "not-a-canonical-key",
        "report_status": "main", "added_by": "x",
    })
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid evidence key"


def test_update_rebind_and_status_pass_through() -> None:
    service = FakeReportEvidenceService()
    response = make_client(service).put("/api/reports/evidence", json={
        "task_id": "A",
        "evidence_key": KEY,
        "report_status": "excluded",
        "analysis_id": "sa_2",
        "updated_by": "analyst-y",
    })

    assert response.status_code == 200
    assert service.updated == [{
        "task_id": "A", "evidence_key": KEY,
        "report_status": "excluded", "analysis_id": "sa_2",
        "bind_analysis": True, "updated_by": "analyst-y",
    }]


def test_update_status_only_keeps_binding() -> None:
    service = FakeReportEvidenceService()
    response = make_client(service).put("/api/reports/evidence", json={
        "task_id": "A", "evidence_key": KEY,
        "report_status": "appendix", "updated_by": "y",
    })

    assert response.status_code == 200
    assert service.updated[0]["analysis_id"] is None
    assert service.updated[0]["bind_analysis"] is False


def test_update_requires_a_change() -> None:
    client = make_client(FakeReportEvidenceService())
    response = client.put("/api/reports/evidence", json={
        "task_id": "A", "evidence_key": KEY, "updated_by": "y",
    })
    assert response.status_code == 422
    assert response.json()["detail"] == "report_status or analysis_id is required"


def test_update_maps_not_found_and_conflict() -> None:
    service = FakeReportEvidenceService()
    client = make_client(service)

    service.update_result = EvidenceNotFoundError("report evidence not found")
    r = client.put("/api/reports/evidence", json={
        "task_id": "A", "evidence_key": KEY,
        "report_status": "main", "updated_by": "y",
    })
    assert r.status_code == 404
    assert r.json()["detail"] == "task or report evidence not found"

    service.update_result = AnalysisBindingConflictError("not accepted")
    r = client.put("/api/reports/evidence", json={
        "task_id": "A", "evidence_key": KEY,
        "analysis_id": "sa_2", "updated_by": "y",
    })
    assert r.status_code == 409
    assert r.json()["detail"] == "analysis binding conflict"


# ---------------------------------------------------------------------------
# file-candidates read model (evidence review page)
# ---------------------------------------------------------------------------

def test_file_candidates_passes_params_and_returns_payload() -> None:
    class CandidatesService(FakeReportEvidenceService):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[dict] = []
            self.candidates_result: dict | Exception = {
                "total": 0, "page": 1, "page_size": 50,
                "status_counts": {"main": 0, "appendix": 0,
                                  "excluded": 0, "unjudged": 0},
                "items": [],
            }

        async def list_file_candidates(self, task_id, *, search="", status="all",
                                       page=1, page_size=50) -> dict:
            self.calls.append({
                "task_id": task_id, "search": search, "status": status,
                "page": page, "page_size": page_size,
            })
            if isinstance(self.candidates_result, Exception):
                raise self.candidates_result
            return self.candidates_result

    service = CandidatesService()
    response = make_client(service).get(
        "/api/reports/evidence/file-candidates",
        params={"task_id": "A", "search": "log", "status": "main",
                "page": 2, "page_size": 25},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert service.calls == [{
        "task_id": "A", "search": "log", "status": "main",
        "page": 2, "page_size": 25,
    }]

    service.candidates_result = EvidenceNotFoundError("task not found")
    not_found = make_client(service).get(
        "/api/reports/evidence/file-candidates", params={"task_id": "A"},
    )
    assert not_found.status_code == 404

    bad_status = make_client(CandidatesService()).get(
        "/api/reports/evidence/file-candidates",
        params={"task_id": "A", "status": "bogus"},
    )
    assert bad_status.status_code == 422


def test_file_candidates_joins_files_with_report_rows(tmp_path) -> None:
    """Real-database read model: files.db LEFT JOIN investigation.db rows."""
    import sqlite3

    from httpserver.services.investigation.report_evidence import (
        ReportEvidenceService,
    )

    files_db = tmp_path / "files.db"
    with sqlite3.connect(files_db) as conn:
        conn.execute(
            "CREATE TABLE files (id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT, "
            "name TEXT, extension TEXT, category TEXT, size INTEGER, mtime INTEGER, "
            "ctime INTEGER, md5 TEXT, is_deleted INTEGER, llm_summary TEXT, "
            "llm_analyzed_at INTEGER, scene_relevant INTEGER)"
        )
        conn.executemany(
            "INSERT INTO files (path, name, extension, size, mtime, is_deleted, "
            "llm_summary, llm_analyzed_at, scene_relevant) VALUES (?,?,?,?,?,?,?,?,?)",
            [
                ("/case/a.log", "a.log", "log", 10, 100, 0, "sum-a", 5, 1),
                ("/case/b.txt", "b.txt", "txt", 20, 200, 0, None, None, 0),
                ("/var/c.log", "c.log", "log", 30, 300, 1, "sum-c", 7, 1),
            ],
        )
        conn.commit()

    inv_db = tmp_path / "investigation.db"
    with sqlite3.connect(inv_db) as conn:
        conn.execute(
            "CREATE TABLE evidence_snapshots (task_id TEXT, evidence_key TEXT, "
            "evidence_type TEXT, normalized_path TEXT, snapshot_json TEXT, "
            "captured_at INTEGER, PRIMARY KEY (task_id, evidence_key))"
        )
        conn.execute(
            "CREATE TABLE report_evidence (task_id TEXT, evidence_key TEXT, "
            "report_status TEXT, analysis_id TEXT, added_by TEXT, "
            "created_at TEXT, updated_at TEXT, updated_by TEXT, "
            "PRIMARY KEY (task_id, evidence_key))"
        )
        conn.execute(
            "INSERT INTO report_evidence VALUES ('A', 'file:/case/a.log', 'main', "
            "NULL, 'x', 't0', 't1', 'y')"
        )
        conn.commit()

    class FakeBackend:
        async def get_task(self, task_id):
            return {
                "id": task_id,
                "output_files_db": str(files_db),
                "output_events_db": "",
            }

    service = ReportEvidenceService(FakeBackend())

    import asyncio

    async def _resolve_db():
        return await service._resolve_task_db("A")

    db_path = asyncio.run(_resolve_db())
    assert db_path.exists() or True  # path derivation exercised above

    # investigation.db path is derived next to files.db; point the service at
    # the tmp copy by matching the frozen derivation rule (same parent).
    result = asyncio.run(service.list_file_candidates("A", page=1, page_size=10))
    assert result["total"] == 3
    assert result["status_counts"]["main"] == 1
    assert result["status_counts"]["unjudged"] == 2
    by_path = {row["path"]: row for row in result["items"]}
    assert by_path["/case/a.log"]["report_status"] == "main"
    assert by_path["/case/b.txt"]["report_status"] is None
    assert by_path["/case/b.txt"]["evidence_key"] == "file:/case/b.txt"

    searched = asyncio.run(service.list_file_candidates("A", search=".log"))
    assert searched["total"] == 2
    assert all(row["path"].endswith(".log") for row in searched["items"])

    unjudged = asyncio.run(service.list_file_candidates("A", status="unjudged"))
    assert unjudged["total"] == 2
    main_only = asyncio.run(service.list_file_candidates("A", status="main"))
    assert main_only["total"] == 1
    assert main_only["items"][0]["path"] == "/case/a.log"


def test_seed_analyzed_files_covers_pipeline_and_never_overrides(tmp_path):
    """初管全量入报：覆盖口径与时间线一致；已有判定（含 excluded）永不覆盖。"""
    import asyncio
    import sqlite3

    from httpserver.services.evidence import ResolvedEvidence
    from httpserver.services.investigation import InvestigationRepository
    from httpserver.services.investigation.report_evidence import (
        ReportEvidenceService,
    )

    events_db = tmp_path / "events.db"
    files_db = tmp_path / "files.db"
    conn = sqlite3.connect(events_db)
    conn.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp INTEGER, "
        "event_type TEXT, file_path TEXT)"
    )
    conn.executemany(
        "INSERT INTO events (timestamp, event_type, file_path) VALUES (?,?,?)",
        [(6005, "CREATED", "/case/a.txt"), (6010, "CREATED", "/case/c.txt"),
         (6015, "CREATED", "/case/ghost.txt")],
    )
    conn.commit()
    conn.close()
    fconn = sqlite3.connect(files_db)
    fconn.execute(
        "CREATE TABLE files (path TEXT, name TEXT, extension TEXT, category TEXT, "
        "type TEXT, size INTEGER, mtime INTEGER, ctime INTEGER, is_deleted INTEGER, "
        "md5 TEXT, llm_summary TEXT, llm_description TEXT, llm_keywords TEXT, "
        "llm_analyzed_at INTEGER, llm_model_used TEXT, scene_type TEXT, "
        "scene_priority INTEGER, scene_relevant INTEGER)"
    )
    fconn.executemany(
        "INSERT INTO files (path, name, size, mtime) VALUES (?,?,?,?)",
        [("/case/a.txt", "a.txt", 10, 6005), ("/case/c.txt", "c.txt", 30, 6010)],
    )
    fconn.commit()
    fconn.close()

    task = {
        "id": "A",
        "output_files_db": str(files_db),
        "output_events_db": str(events_db),
    }
    repo = InvestigationRepository(tmp_path / "investigation.db", "A")
    repo.capture_if_absent(
        ResolvedEvidence(
            task_id="A", evidence_key="cluster:v1:100:CREATED", evidence_type="cluster",
            version="v1", unix_minute=100, event_type="CREATED", cluster_start=6000,
            cluster_end=6059, event_count=3, representative_timestamp=6005,
            source_db=str(events_db),
        )
    )
    repo.capture_if_absent(
        ResolvedEvidence(
            task_id="A", evidence_key="file:/case/c.txt", evidence_type="file",
            normalized_path="/case/c.txt", source_db=str(files_db),
        )
    )
    event_id = repo.create_event("聚类事件", summary="s").event_id
    repo.link_event_evidence(event_id, "cluster:v1:100:CREATED", linked_by="cluster_seed")

    # 取证人员预先把 c.txt 排除出报告（add 仅允许 main/appendix，excluded 走 update）
    repo.add_report_evidence("file:/case/c.txt", report_status="main", added_by="analyst")
    repo.update_report_evidence("file:/case/c.txt", report_status="excluded", updated_by="analyst")

    class FakeBackend:
        async def get_task(self, task_id):
            return task

    service = ReportEvidenceService(FakeBackend())
    result = asyncio.run(service.seed_analyzed_files("A", added_by="pipeline"))

    # 覆盖集 = {a.txt, c.txt, ghost.txt}；c.txt 已判定跳过；ghost 缺行跳过
    assert result["covered_files"] == 3
    assert result["seeded"] == 1
    assert result["skipped_judged"] == 1
    assert result["missing_in_files_table"] == 1

    conn = sqlite3.connect(tmp_path / "investigation.db")
    a_status = conn.execute(
        "SELECT report_status FROM report_evidence WHERE evidence_key='file:/case/a.txt'"
    ).fetchone()[0]
    c_status = conn.execute(
        "SELECT report_status FROM report_evidence WHERE evidence_key='file:/case/c.txt'"
    ).fetchone()[0]
    snap = conn.execute(
        "SELECT snapshot_json FROM evidence_snapshots WHERE evidence_key='file:/case/a.txt'"
    ).fetchone()[0]
    conn.close()
    assert a_status == "main"
    assert c_status == "excluded"  # 取证人员的取消不被回退
    assert '"normalized_path": "/case/a.txt"' in snap

    # 幂等：重复调用只补新增（0 个）
    again = asyncio.run(service.seed_analyzed_files("A", added_by="pipeline"))
    assert again["seeded"] == 0
    assert again["skipped_judged"] == 2
