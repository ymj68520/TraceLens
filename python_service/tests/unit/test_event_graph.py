import asyncio
import copy
import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes.graphiti_endpoints import _events
from httpserver.services.evidence.models import ResolvedEvidence
from httpserver.services.event_graph.models import StartRequest, ViewFilter
from httpserver.services.event_graph.service import EventGraphService
from httpserver.services.event_graph.inference import bind_people
from httpserver.services.event_graph.snapshot import read_snapshot
from httpserver.services.investigation.repository import InvestigationRepository
from httpserver.services.people_graph.models import digest
from httpserver.services.people_graph.service import PeopleGraphService
from httpserver.services.people_graph.sources import catalog
from httpserver.services.people_graph.storage import PeopleGraphStore, RunConflict
from httpserver.services.field_security import required_permission

TEXT = "张三安排李四支付货款，收款时间与后续记录需要核对。"


class Model:
    def __init__(self):
        self.calls = []
        self.malicious = False
        self.fail = False

    async def chat_completion(self, **kwargs):
        data = json.loads(kwargs["user_prompt"])
        self.calls.append(data)
        if self.fail:
            raise TimeoutError("synthetic")
        pair = data["pair"]
        refs = [{"source_id": s["source_id"], "quote": s["text"]} for s in data["sources"]]
        if self.malicious:
            refs = [{"source_id": "evidence:file:/foreign.txt", "quote": "伪造材料"}]
        kind = "participation_candidate" if pair["type"] == "person_event" else "related_candidate"
        return {"model": "synthetic-event-model", "content": json.dumps({"suggestions": [
            {"kind": kind, "reason": "材料存在付款线索，需要核查人员身份和事件关系。", "refs": refs}
        ]}, ensure_ascii=False)}


@pytest.fixture
def setup(tmp_path):
    files = tmp_path / "files.db"
    raw = TEXT.encode()
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    (extracted / "a.txt").write_bytes(raw)
    md5 = hashlib.md5(raw).hexdigest()
    with sqlite3.connect(files) as conn:
        conn.execute("""CREATE TABLE files (path TEXT,name TEXT,extension TEXT,category TEXT,type TEXT,size INTEGER,
                     mtime INTEGER,ctime INTEGER,is_deleted INTEGER,md5 TEXT,llm_summary TEXT,llm_description TEXT,
                     llm_keywords TEXT,llm_analyzed_at INTEGER,llm_model_used TEXT,scene_type TEXT,scene_priority INTEGER,scene_relevant INTEGER)""")
        conn.execute("INSERT INTO files(path,name,md5,size,llm_summary,mtime,ctime) VALUES (?,?,?,?,?,?,?)",
                     ("/a.txt", "a.txt", md5, len(raw), TEXT, 100, 200))
    task = {"id": "T", "output_files_db": str(files), "extraction_directory": str(extracted), "case_description": "待核案情"}
    cpp = SimpleNamespace(get_task=AsyncMock(side_effect=lambda tid: {**task, "id": tid} if tid in ("T", "U") else None))
    model = Model()
    manager = PeopleGraphService(cpp, model, lambda: None)
    service = EventGraphService(manager)
    repo = InvestigationRepository(tmp_path / "investigation.db", "T")
    repo.capture_if_absent(ResolvedEvidence(task_id="T", evidence_key="file:/a.txt", evidence_type="file",
                                          normalized_path="/a.txt", source_db=str(files)))
    events = [repo.create_event(title=name) for name in ("付款安排", "后续收款", "孤立事件")]
    for event in events[:2]:
        repo.link_event_evidence(event.event_id, "file:/a.txt")
    store = PeopleGraphStore(tmp_path / "investigation.db", "T")
    base = store.admit({"case_description": "", "task_case_hash": digest("待核案情")}, "tester", manager.epoch, "discover")
    _, _, revision = catalog(task, 200)
    result = {"people": [{"id": "p1", "name": "张三", "identity_status": "candidate", "mention_ids": ["m1"]}],
              "materials": [{"id": "mat1", "evidence_key": "file:/a.txt", "text": TEXT,
                             "source_hash": hashlib.sha256(raw).hexdigest(), "source_md5": md5, "kind": "text"}],
              "mentions": [{"id": "m1", "name": "张三", "ref": {"source_id": "mat1", "quote": TEXT, "start": 0}}],
              "catalog_revision": revision, "coverage": {"file_limit": 200}, "annotations": {}}
    store.finish(base["run_id"], result)
    return service, manager, task, repo, events, base["run_id"], model


async def complete(setup, **overrides):
    service, manager, _, _, _, people_id, _ = setup
    run = await service.start(StartRequest(task_id="T", people_run_id=people_id, requested_by="tester", **overrides), "tester")
    await asyncio.gather(*list(manager._tasks.values()))
    _, _, stored = await service._run("T", run["run_id"])
    assert stored["status"] == "completed", stored.get("error")
    return stored


@pytest.mark.asyncio
async def test_live_reads_keep_isolated_events_and_share_exact_evidence(setup):
    service, _, _, repo, events, _, model = setup
    before = repo.list_events()
    graph = await service.live("T", ViewFilter())
    assert len([n for n in graph["nodes"] if n["kind"] == "event"]) == 3
    assert any(n["name"] == "孤立事件" for n in graph["nodes"])
    shared = [e for e in graph["links"] if e["kind"] == "shared_evidence"]
    assert len(shared) == 1 and shared[0]["source_ids"] == ["evidence:file:/a.txt"]
    detail = await service.detail("T", shared[0]["id"], source_version=graph["source_version"])
    assert detail["sources"][0]["payload"]["initial_summary"] == TEXT
    assert {n["name"] for n in detail["target"]["endpoints"]} == {"付款安排", "后续收款"}
    assert model.calls == [] and repo.list_events() == before
    assert (await service.live("U", ViewFilter()))["nodes"] == []


@pytest.mark.asyncio
async def test_get_never_creates_store(tmp_path):
    task = {"id": "T", "output_files_db": str(tmp_path / "absent" / "files.db")}
    manager = PeopleGraphService(SimpleNamespace(get_task=AsyncMock(return_value=task)), Model(), lambda: None)
    service = EventGraphService(manager)
    assert (await service.live("T", ViewFilter()))["nodes"] == []
    assert await service.list_runs("T") == []
    assert not (tmp_path / "absent").exists()


@pytest.mark.asyncio
async def test_filters_before_limit_and_list_independent(setup):
    service = setup[0]
    full = await service.live("T", ViewFilter(max_nodes=1))
    assert full["display_truncated"] and full["total_items"] > 1
    selected = await service.live("T", ViewFilter(query="孤立", max_nodes=1))
    assert len(selected["nodes"]) == 1 and selected["nodes"][0]["name"] == "孤立事件"
    assert selected["links"] == []
    page = await service.live("T", ViewFilter(max_nodes=1, offset=1, limit=1))
    assert page["items"][0] == full["items"][1]


@pytest.mark.asyncio
async def test_live_trace_rejects_changed_source_version(setup):
    service, _, _, repo, _, _, _ = setup
    graph = await service.live("T", ViewFilter())
    repo.create_event(title="新增事件")
    with pytest.raises(RunConflict):
        await service.detail("T", graph["nodes"][0]["id"], source_version=graph["source_version"])


@pytest.mark.asyncio
async def test_frozen_suggestions_bind_versions_and_do_not_write_events(setup):
    service, manager, _, repo, events, people_id, model = setup
    before = [e.model_dump() for e in repo.list_events()]
    run = await complete(setup)
    assert run["input"]["people_run_id"] == people_id
    assert run["input"]["people_result_hash"] and run["input"]["snapshot_hash"]
    assert {e["event_id"] for e in run["input"]["snapshot"]["events"]} == {e.event_id for e in events}
    assert [e.model_dump() for e in repo.list_events()] == before
    result = run["result"]
    assert any(e["kind"] == "participation_candidate" for e in result["links"])
    assert any(e["kind"] == "related_candidate" for e in result["links"])
    assert result["coverage"]["insufficient_source_pairs"] == 2
    assert all(e["status"] == "machine_suggestion" for e in result["links"] if e["kind"] != "mentioned_in")
    assert not any(r["run_id"] == run["run_id"] for r in await manager.list_runs("T"))
    with pytest.raises(FileNotFoundError):
        await manager.status("T", run["run_id"])
    with pytest.raises(FileNotFoundError):
        await service.status("T", people_id)
    with pytest.raises(FileNotFoundError):
        await service.status("U", run["run_id"])
    calls = len(model.calls)
    repo.create_event(title="后来登记的事件")
    graph = await service.graph("T", run["run_id"], ViewFilter(view="associations"))
    assert graph["freshness"]["investigation"] == "changed"
    target = next(e for e in result["links"] if e["kind"] == "participation_candidate")
    detail = await service.detail("T", target["id"], run_id=run["run_id"])
    assert detail["target"]["refs"][0]["snapshot_hash"]
    assert len(model.calls) == calls
    _, store, _ = await service._run("T", run["run_id"])
    with store._connect(True) as db, pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE graph_analysis_runs SET result_json='{}' WHERE run_id=?", (run["run_id"],))


@pytest.mark.asyncio
@pytest.mark.parametrize("malicious,fail", [(True, False), (False, True)])
async def test_bad_quotes_and_failed_calls_are_visible_not_relations(setup, malicious, fail):
    model = setup[-1]
    model.malicious, model.fail = malicious, fail
    result = (await complete(setup))["result"]
    assert all(e["kind"] == "mentioned_in" for e in result["links"])
    assert result["coverage"]["invalid_suggestions" if malicious else "failed_pairs"] > 0


@pytest.mark.asyncio
async def test_budget_omissions_and_selected_event_scope(setup):
    events = setup[4]
    run = await complete(setup, event_ids=[e.event_id for e in events[:2]], max_pairs=1)
    assert run["result"]["coverage"]["omitted_pairs"] == 2
    assert run["result"]["coverage"]["events_not_selected"] == 1
    assert all(e["target"] != f"event:{events[2].event_id}" for e in run["result"]["links"])


@pytest.mark.asyncio
async def test_cancel_before_worker_and_shared_shutdown(setup):
    service, manager, _, _, _, pid, _ = setup
    request = StartRequest(task_id="T", people_run_id=pid, requested_by="tester")
    await manager._slots.acquire()
    run = await service.start(request, "tester")
    with pytest.raises(RunConflict):
        await service.start(request, "tester")
    assert (await service.cancel("T", run["run_id"]))["status"] == "cancelled"
    run2 = await service.start(request, "tester")
    await manager.shutdown()
    assert (await service.status("T", run2["run_id"]))["status"] == "cancelled"
    manager._slots.release()
    with pytest.raises(RunConflict):
        await service.start(request, "tester")


@pytest.mark.asyncio
async def test_reject_wrong_person_run_and_event_selection(setup):
    service, _, _, _, _, pid, _ = setup
    with pytest.raises(ValueError):
        await service.start(StartRequest(task_id="T", requested_by="tester", event_ids=["foreign"]), "tester")
    with pytest.raises(ValueError):
        await service.start(StartRequest(task_id="U", requested_by="tester", people_run_id=pid), "tester")


def test_source_counts_and_old_schema_are_not_hidden(setup, monkeypatch):
    _, _, _, repo, _, _, _ = setup
    from httpserver.services.event_graph import snapshot
    monkeypatch.setattr(snapshot, "EVENT_LIMIT", 1)
    graph = read_snapshot(Path(setup[2]["output_files_db"]).parent / "investigation.db", "T")
    assert graph["coverage"]["events_total"] == 3
    assert graph["coverage"]["events_captured"] == 1 and graph["coverage"]["truncated"]


def test_routes_validate_and_inventory(setup, monkeypatch):
    monkeypatch.setattr(_events, "service", lambda: setup[0])
    app = FastAPI()
    app.include_router(_events.router, prefix="/api/graphiti")
    client = TestClient(app)
    assert client.get("/api/graphiti/event-views", params={"task_id": "T"}).status_code == 200
    assert client.get("/api/graphiti/event-views?task_id=T&view=other").status_code == 422
    assert client.get("/api/graphiti/event-views?task_id=T&relation_kind=unknown").status_code == 422
    assert client.get("/api/graphiti/event-views?task_id=T&query=a&query=b").status_code == 422
    assert client.post("/api/graphiti/event-analysis/runs", json={"task_id": "T", "requested_by": "x", "db_path": "/bad"}).status_code == 422
    inventory = json.loads((Path(__file__).resolve().parents[3] / "docs/field-protected-routes.json").read_text())
    for route in _events.router.routes:
        for method in route.methods:
            path = "/api/graphiti" + route.path
            assert {"method": method, "path": path, "permission": required_permission(method, path)} in inventory["python"]


@pytest.mark.asyncio
async def test_legacy_people_bytes_verified_and_mismatched_versions_never_participate(setup):
    service, manager, task, _, _, pid, _ = setup
    _, _, snapshot = await service._snapshot("T")
    _, _, original = await manager._run("T", pid)
    legacy = copy.deepcopy(original)
    legacy["result"]["materials"][0].pop("source_md5")
    bound = await bind_people(task, snapshot, legacy)
    assert bound["sources"][0]["binding_verified"] is True
    assert bound["legacy_byte_checks"] == 1
    (Path(task["extraction_directory"]) / "a.txt").write_text("改变后的材料", encoding="utf-8")
    mismatched = await bind_people(task, snapshot, legacy)
    assert mismatched["unverified_bindings"] == 1
    from httpserver.services.event_graph.inference import candidates
    pairs, _ = candidates(snapshot, mismatched)
    assert all(p["type"] != "person_event" for p in pairs)
    assert all(e["binding_verified"] is False for e in mismatched["mention_links"])


@pytest.mark.asyncio
async def test_evidence_view_keeps_captured_unlinked_material(setup):
    service, _, task, repo, _, _, _ = setup
    with sqlite3.connect(task["output_files_db"]) as db:
        db.execute("INSERT INTO files(path,name,size) VALUES ('/orphan.txt','未关联材料',0)")
    repo.capture_if_absent(ResolvedEvidence(task_id="T", evidence_key="file:/orphan.txt", evidence_type="file",
                                          normalized_path="/orphan.txt", source_db=task["output_files_db"]))
    graph = await service.live("T", ViewFilter(view="evidence"))
    assert any(n["id"] == "evidence:file:/orphan.txt" for n in graph["nodes"])
    events = await service.live("T", ViewFilter(view="events"))
    assert not any(n["id"] == "evidence:file:/orphan.txt" for n in events["nodes"])


@pytest.mark.asyncio
async def test_event_revision_is_frozen_and_new_person_version_flagged(setup):
    service, manager, _, repo, events, pid, _ = setup
    run = await complete(setup)
    # Simulate an independently completed event refresh by appending its narrative.
    with repo._connect() as db:
        db.execute("INSERT INTO investigation_event_versions(task_id,event_id,version,title,summary,created_at,created_by) "
                   "VALUES ('T',?,2,'新标题','更新叙述','2026-10-21','tester')", (events[0].event_id,))
    _, store, original = await manager._run("T", pid)
    next_run = store.admit(original["input"], "tester", manager.epoch, "identity_review", pid)
    store.finish(next_run["run_id"], original["result"])
    graph = await service.graph("T", run["run_id"], ViewFilter())
    assert graph["freshness"]["newer_people_version"]
    assert graph["freshness"]["investigation"] == "changed"
    assert not any(n["name"] == "新标题" for n in graph["nodes"])
