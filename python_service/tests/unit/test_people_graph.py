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

from httpserver.routes.graphiti_endpoints import _people
from httpserver.services.people_graph.models import GraphFilter, IdentityRequest, StartRequest
from httpserver.services.people_graph.service import PeopleGraphService
from httpserver.services.people_graph.storage import PeopleGraphStore, RunConflict
from httpserver.services.people_graph.inference import (
    assess, build_people, discover, project_identities, unassessed, valid_identity_number,
)
from httpserver.services.people_graph.projection import identity_revision, project
from httpserver.services.people_graph.sources import read_materials
from httpserver.services.field_security import required_permission

A = "张三（身份证11010519491231002X）安排李四付款。王五独自签收。root是系统账号。"
B = "张三在另一单位任职。赵六独自签收。"


class FakeLLM:
    def __init__(self):
        self.calls = []
        self.bad_quote = False
        self.wait = None

    async def chat_completion(self, **kwargs):
        payload = json.loads(kwargs["user_prompt"])
        self.calls.append(payload)
        if self.wait:
            await self.wait.wait()
        if "material_id" in payload:
            text = payload["text"]
            people, relations = [], []
            if "另一单位" in text:
                people = [{"local_id": "a", "name": "张三", "kind": "person", "quote": "张三在另一单位任职。"},
                          {"local_id": "b", "name": "赵六", "kind": "person", "quote": "赵六独自签收。"}]
            elif "安排李四" in text:
                q = text.split("。")[0] + "。"
                people = [
                    {"local_id": "a", "name": "张三", "kind": "person", "quote": q,
                     "identity_number": "11010519491231002X", "identity_quote": q},
                    {"local_id": "b", "name": "李四", "kind": "person", "quote": q},
                    {"local_id": "c", "name": "王五", "kind": "person", "quote": "王五独自签收。"},
                    {"local_id": "root", "name": "root", "kind": "account", "quote": "root是系统账号。"},
                ]
                relations = [{"source": "a", "target": "b", "label": "安排付款", "kind": "direct", "quote": q}]
            body = {"people": people, "relations": relations}
        else:
            items = []
            for t in payload["targets"]:
                important = "张三" in t["name"] or "付款" in t["name"]
                q = payload["questions"][0]["question_id"]
                source = t["sources"][0]
                items.append({"target_id": t["id"], "relations": [{"question_id": q,
                              "relation": "supports" if important else "background"}],
                              "key_issue": important, "core_candidate": t["kind"] == "person" and important,
                              "reason": "来源记载付款安排，需核对原文及身份。" if important else "当前属于背景材料。",
                              "refs": [{"source_id": source["source_id"], "quote": "伪造的来源" if self.bad_quote else source["text"]}]})
            body = {"items": items}
        return {"content": json.dumps(body, ensure_ascii=False), "model": "synthetic-people-model", "finish_reason": "stop"}


class FakeGraph:
    def __init__(self):
        self.value = {
            "relations": [
                {"id": "graph-1", "source": "node-a", "target": "node-b", "source_name": "张三",
                 "target_name": "李四", "label": "安排付款", "fact": "机器关系表述",
                 "episode_ids": ["ep-1"]},
                {"id": "graph-case", "source": "node-c", "target": "node-d", "source_name": "案情甲",
                 "target_name": "案情乙", "label": "案情假设", "fact": "只在案情中出现", "episode_ids": ["ep-case"]},
            ],
            "episodes": [
                {"id": "ep-1", "text": "张三安排李四付款。", "kind": "initial_analysis", "truncated": False},
                {"id": "ep-case", "text": "案情认为甲联系乙。", "kind": "case_description", "truncated": False},
            ],
            "coverage": {"total_relations": 2, "captured_relations": 2, "relation_limit": 500,
                         "unread_or_missing_episodes": 0, "episode_text_truncated": 0},
        }

    async def get_priority_snapshot(self, *_):
        return copy.deepcopy(self.value)


@pytest.fixture
def setup(tmp_path):
    directory = tmp_path / "T"
    directory.mkdir()
    extracted = directory / "extracted_files"
    extracted.mkdir()
    files = directory / "files.db"
    with sqlite3.connect(files) as db:
        db.execute("CREATE TABLE files(id INTEGER PRIMARY KEY,path TEXT,size INTEGER,md5 TEXT)")
        for i, (name, text) in enumerate((("a.txt", A), ("b.txt", B))):
            raw = text.encode()
            (extracted / name).write_bytes(raw)
            # No AI-analysis or report-adoption fields: unanalysed files must be included.
            db.execute("INSERT INTO files VALUES (?,?,?,?)", (i + 1, "/" + name, len(raw), hashlib.md5(raw).hexdigest()))
    task = {"id": "T", "output_files_db": str(files), "extraction_directory": str(extracted),
            "case_description": "核查张三安排付款及资金去向。"}
    cpp = SimpleNamespace(get_task=AsyncMock(side_effect=lambda tid: task if tid == "T" else None))
    llm, graph = FakeLLM(), FakeGraph()
    service = PeopleGraphService(cpp, llm, lambda: graph)
    return service, task, llm, graph


async def complete(service, request=None):
    run = await service.start(request or StartRequest(task_id="T"), "tester")
    await asyncio.gather(*list(service._tasks.values()))
    _, store, row = await service._run("T", run["run_id"])
    assert row["status"] == "completed", row
    return row


@pytest.mark.asyncio
async def test_discover_all_registered_people_without_case_in_discovery(setup):
    service, task, llm, _ = setup
    run = await complete(service)
    result = run["result"]
    assert result["coverage"]["registered_files"] == result["coverage"]["complete_files"] == 2
    assert len(result["people"]) == 5
    assert {p["name"] for p in result["people"]} == {"张三", "李四", "王五", "赵六"}
    assert sum(p["name"] == "张三" for p in result["people"]) == 2
    assert all("root" not in p["names"] for p in result["people"])
    discovery_calls = [c for c in llm.calls if "material_id" in c]
    assert len(discovery_calls) == 2
    assert all("case_description" not in c and "核查张三" not in json.dumps(c, ensure_ascii=False) for c in discovery_calls)
    assert len(result["person_relations"]) == 1
    assert sum(p["relation_count"] == 0 for p in result["people"]) == 3
    assert result["coverage"]["exhaustive_people_claim"] is False


@pytest.mark.asyncio
async def test_person_and_relationship_priorities_have_independent_grounded_sources(setup):
    service, _, _, _ = setup
    run = await complete(service)
    result = run["result"]
    assert result["annotations"]["graph-1"]["priority"] == "P1"
    assert result["annotations"]["graph-case"]["priority"] == "unassessed"
    assert result["annotations"]["graph-case"]["status"] == "insufficient"
    core = [p for p in result["people"] if result["annotations"][p["id"]]["core"]]
    assert len(core) == 1 and core[0]["identity_status"] == "recorded_identifier"
    other = next(p for p in result["people"] if p["name"] == "李四")
    assert result["annotations"][other["id"]]["priority"] == "P3"
    materials = {m["id"]: m for m in [*result["materials"], *result["graph_episodes"]]}
    for a in result["annotations"].values():
        for ref in a["refs"]:
            assert materials[ref["source_id"]]["text"][ref["start"]:ref["end"]] == ref["quote"]


@pytest.mark.asyncio
async def test_no_case_keeps_people_unassessed_and_never_invents_core(setup):
    service, _, llm, _ = setup
    run = await complete(service, StartRequest(task_id="T", case_description=""))
    assert run["result"]["people"]
    assert not any(a["core"] for a in run["result"]["annotations"].values())
    assert all("targets" not in c for c in llm.calls)


@pytest.mark.asyncio
async def test_invalid_priority_quote_is_not_accepted_as_low_priority(setup):
    service, _, llm, _ = setup
    llm.bad_quote = True
    run = await complete(service)
    assert all(a["priority"] == "unassessed" for a in run["result"]["annotations"].values())
    assert any(a["status"] == "failed" for a in run["result"]["annotations"].values())


@pytest.mark.asyncio
async def test_missing_graph_does_not_erase_people_or_claim_graph_is_empty(setup):
    service, _, _, graph = setup
    graph.get_priority_snapshot = AsyncMock(side_effect=RuntimeError("offline"))
    run = await complete(service)
    assert len(run["result"]["people"]) == 5
    assert run["result"]["graph_coverage"]["available"] is False


@pytest.mark.asyncio
async def test_missing_files_and_limits_are_disclosed(setup):
    service, task, _, _ = setup
    Path(task["extraction_directory"], "b.txt").unlink()
    run = await complete(service)
    assert run["result"]["coverage"]["unavailable_files"] == 1
    run2 = await complete(service, StartRequest(task_id="T", max_files=1, max_assessments=1))
    assert run2["result"]["coverage"]["unprocessed_files"] == 1
    assert run2["result"]["assessment_coverage"]["truncated"] is True


@pytest.mark.asyncio
async def test_assessment_reuses_frozen_materials_and_continues_pending_scope(setup):
    service, task, llm, _ = setup
    first = await complete(service, StartRequest(task_id="T", max_assessments=1))
    discovery_count = sum("material_id" in c for c in llm.calls)
    second = await complete(service, StartRequest(task_id="T", mode="assess", base_run_id=first["run_id"], max_assessments=100))
    assert sum("material_id" in c for c in llm.calls) == discovery_count
    assert second["result"]["materials"] == first["result"]["materials"]
    assert second["result"]["assessment_coverage"]["pending"] < first["result"]["assessment_coverage"]["pending"]
    Path(task["extraction_directory"], "a.txt").write_text("changed", encoding="utf-8")
    state = await service.status("T", first["run_id"])
    assert state["freshness"]["materials_changed"]
    detail = await service.detail("T", first["run_id"], first["result"]["people"][0]["id"])
    assert "张三" in detail["sources"][0]["text"]


@pytest.mark.asyncio
async def test_case_change_resets_old_scores_but_preserves_discovery(setup):
    service, _, llm, _ = setup
    first = await complete(service)
    second = await complete(service, StartRequest(task_id="T", mode="assess", base_run_id=first["run_id"], case_description=""))
    assert second["result"]["mentions"] == first["result"]["mentions"]
    assert all(a["priority"] == "unassessed" for a in second["result"]["annotations"].values())


@pytest.mark.asyncio
async def test_identity_merge_split_versions_are_immutable_and_clear_person_scores(setup):
    service, task, _, _ = setup
    first = await complete(service)
    ids = [p["id"] for p in first["result"]["people"] if p["name"] == "张三"]
    merged = await service.revise_identity("T", first["run_id"], IdentityRequest(
        operation="merge", person_ids=ids, reason="合成材料经人工核查", display_name="张三"), "reviewer")
    _, store, second = await service._run("T", merged["run_id"])
    assert len(second["result"]["people"]) == 4
    assert len((await asyncio.to_thread(store.get, first["run_id"]))["result"]["people"]) == 5
    person = next(p for p in second["result"]["people"] if p["identity_status"] == "manually_grouped")
    assert person["id"] not in second["result"]["annotations"]
    split = await service.revise_identity("T", second["run_id"], IdentityRequest(
        operation="split", person_ids=[person["id"]], mention_ids=person["mention_ids"][:1], reason="区分不同身份"), "reviewer")
    _, _, third = await service._run("T", split["run_id"])
    assert len(third["result"]["people"]) == 5
    assert len(third["result"]["identity_history"]) == 2
    with sqlite3.connect(store.path) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE graph_analysis_runs SET result_json='{}' WHERE run_id=?", (first["run_id"],))
        from httpserver.services.investigation.repository import SUPPORTED_SCHEMA_VERSION
        assert db.execute("PRAGMA user_version").fetchone()[0] == SUPPORTED_SCHEMA_VERSION


@pytest.mark.asyncio
async def test_manual_group_carries_only_unchanged_mentions(setup):
    service, _, _, _ = setup
    first = await complete(service)
    ids = [p["id"] for p in first["result"]["people"] if p["name"] == "张三"]
    merged = await service.revise_identity("T", first["run_id"], IdentityRequest(operation="merge", person_ids=ids, reason="核查"), "reviewer")
    refreshed = await complete(service, StartRequest(task_id="T", base_run_id=merged["run_id"]))
    assert refreshed["result"]["coverage"]["identity_groups_carried"] == 1
    assert len(refreshed["result"]["people"]) == 4


@pytest.mark.asyncio
async def test_graph_filters_apply_before_viewport_and_keep_context_distinct(setup):
    service, _, _, _ = setup
    run = await complete(service)
    r = run["result"]
    projection = project(r, GraphFilter(view="relations", priority="P1", max_nodes=2))
    assert [e["id"] for e in projection["links"]] == ["graph-1"]
    assert all(n["assessment"]["priority"] == "unassessed" for n in projection["nodes"])
    only_core = project(r, GraphFilter(priority="core", include_context=False))
    assert len(only_core["nodes"]) == 1
    expanded = project(r, GraphFilter(priority="core", include_context=True))
    assert any(n.get("context_only") for n in expanded["nodes"])
    assert all(link["context_only"] for link in expanded["links"])
    assert project(r, GraphFilter(identity_status="isolated"))["total_items"] == 3
    small = project(r, GraphFilter(max_nodes=1, limit=2))
    assert small["display_truncated"] and small["total_items"] == 5 and len(small["items"]) == 2


@pytest.mark.asyncio
async def test_cross_task_and_unknown_target_cannot_read_foreign_run(setup):
    service, _, _, _ = setup
    run = await complete(service)
    with pytest.raises(FileNotFoundError):
        await service.graph("foreign", run["run_id"], GraphFilter())
    with pytest.raises(FileNotFoundError):
        await service.detail("T", run["run_id"], "invented")
    with pytest.raises(ValueError):
        await service.graph("T", run["run_id"], GraphFilter(question_id="foreign-question"))


@pytest.mark.asyncio
async def test_get_without_store_never_creates_or_starts_analysis(setup):
    service, task, llm, _ = setup
    assert await service.list_runs("T") == []
    assert not (Path(task["output_files_db"]).parent / "investigation.db").exists()
    assert not llm.calls


@pytest.mark.asyncio
async def test_single_flight_cancellation_and_shutdown_have_terminal_state(setup):
    service, _, llm, _ = setup
    llm.wait = asyncio.Event()
    first = await service.start(StartRequest(task_id="T"), "tester")
    await asyncio.sleep(0)
    with pytest.raises(RunConflict):
        await service.start(StartRequest(task_id="T"), "tester")
    await service.shutdown()
    status = await service.status("T", first["run_id"])
    assert status["status"] == "cancelled"
    with pytest.raises(RunConflict):
        await service.start(StartRequest(task_id="T"), "tester")


def test_restart_interruption_is_visible_and_new_admission_recovers(tmp_path):
    store = PeopleGraphStore(tmp_path / "investigation.db", "T")
    frozen = {"case_description": "", "task_case_hash": "x"}
    old = store.admit(frozen, "actor", "old-process", "discover")
    fresh = store.admit(frozen, "actor", "new-process", "discover")
    assert store.get(old["run_id"])["status"] == "failed"
    assert store.get(fresh["run_id"])["status"] == "running"


def test_identity_number_gate_does_not_group_arbitrary_phone_or_employee_number():
    assert valid_identity_number("11010519491231002X")
    assert not valid_identity_number("13800138000")
    assert not valid_identity_number("employee12345")
    assert not valid_identity_number("110105194912310021")


def test_conflicting_names_with_same_identifier_remain_distinct():
    mentions = [{"id": "m1", "name": "张三", "identity_number": "11010519491231002X"},
                {"id": "m2", "name": "李四", "identity_number": "11010519491231002X"}]
    people, relations = build_people("T", mentions, [])
    assert len(people) == 2 and not relations
    assert all(p["identity_status"] == "identity_conflict" for p in people)


def test_public_run_uses_persisted_policy_version():
    service = PeopleGraphService(None, None, None)
    result = service._public({"input": {"case_description": "", "policy_version": "old-policy"},
                              "status": "completed", "owner_epoch": "old"})
    assert result["policy_version"] == "old-policy"


def test_people_routes_are_in_protected_inventory():
    inventory = json.loads((Path(__file__).resolve().parents[3] / "docs/field-protected-routes.json").read_text())
    expected = [
        ("GET", "/api/graphiti/people-analysis/runs"),
        ("POST", "/api/graphiti/people-analysis/runs"),
        ("GET", "/api/graphiti/people-analysis/runs/{run_id}"),
        ("POST", "/api/graphiti/people-analysis/runs/{run_id}/cancel"),
        ("GET", "/api/graphiti/people-analysis/runs/{run_id}/graph"),
        ("POST", "/api/graphiti/people-analysis/runs/{run_id}/identity/review"),
        ("GET", "/api/graphiti/people-analysis/runs/{run_id}/targets/{target_id}"),
    ]
    for method, route in expected:
        assert {"method": method, "path": route, "permission": required_permission(method, route)} in inventory["python"]


@pytest.mark.asyncio
async def test_false_person_and_foreign_relation_are_not_adopted():
    llm = SimpleNamespace(chat_completion=AsyncMock(return_value={"model": "fake", "content": json.dumps({
        "people": [{"local_id": "a", "name": "不存在的人", "kind": "person", "quote": "王五独自签收。"}],
        "relations": [{"source": "a", "target": "foreign", "kind": "direct", "label": "转账", "quote": "王五独自签收。"}],
    }, ensure_ascii=False)}))
    material = {"id": "m", "text": "王五独自签收。", "kind": "text", "status": "complete", "source_hash": "x", "limitations": []}
    people, relations, coverage, _ = await discover("T", [material], llm, AsyncMock())
    assert not people and not relations and material["status"] == "partial"


def test_identity_review_uses_existing_review_permission():
    assert required_permission("POST", "/api/graphiti/people-analysis/runs/x/identity/review") == "review"


def test_routes_do_not_start_jobs_on_read_and_validate_filters(monkeypatch):
    fake = SimpleNamespace(list_runs=AsyncMock(return_value=[]), start=AsyncMock(), graph=AsyncMock(return_value={}))
    monkeypatch.setattr(_people, "service", lambda: fake)
    app = FastAPI()
    app.include_router(_people.router, prefix="/api/graphiti")
    client = TestClient(app)
    assert client.get("/api/graphiti/people-analysis/runs?task_id=T").json() == {"runs": []}
    fake.start.assert_not_called()
    assert client.get("/api/graphiti/people-analysis/runs/x/graph?task_id=T&priority=unknown-grade").status_code == 422
    assert client.get("/api/graphiti/people-analysis/runs/x/graph?task_id=T&arbitrary_path=x").status_code == 422
    assert client.post("/api/graphiti/people-analysis/runs", json={"task_id": "T", "db_path": "/secret"}).status_code == 422


@pytest.mark.asyncio
async def test_cancel_before_worker_first_instruction_closes_durable_row(setup):
    service, _, llm, _ = setup
    llm.wait = asyncio.Event()
    service._slots = asyncio.Semaphore(0)
    run = await service.start(StartRequest(task_id="T"), "tester")
    status = await service.cancel("T", run["run_id"])
    assert status["status"] == "cancelled"


@pytest.mark.asyncio
async def test_priority_snapshot_uses_stable_task_edges_and_marks_partial_sources():
    from httpserver.services.graphiti_parts._query import GraphitiQueryMixin
    reader = GraphitiQueryMixin()
    reader._run_read_query = AsyncMock(side_effect=[
        [{"total": 1001}],
        [{"id": "r", "source": "a", "target": "b", "source_name": "甲", "target_name": "乙",
          "label": "联系", "fact": "甲联系乙", "episode_ids": ["e", "missing", "e"]}],
        [{"id": "e", "text": "案情" * 3000, "source_description": "用户提供的案情描述 - 第1部分"}],
    ])
    snapshot = await reader.get_priority_snapshot("task-X", 500)
    assert snapshot["coverage"]["total_relations"] == 1001
    assert snapshot["coverage"]["unread_or_missing_episodes"] == 1
    assert snapshot["coverage"]["episode_text_truncated"] == 1
    assert snapshot["episodes"][0]["kind"] == "case_description"
    assert len(snapshot["episodes"][0]["text"]) == 4000
    assert "ORDER BY r.uuid" in reader._run_read_query.call_args_list[1].args[0]
    assert all(call.args[1]["gid"] == "task-X" for call in reader._run_read_query.call_args_list)


@pytest.mark.asyncio
async def test_pending_targets_are_not_starved_by_unreadable_old_targets(setup):
    service, _, _, _ = setup
    run = await complete(service, StartRequest(task_id="T", max_assessments=1))
    for _ in range(6):
        run = await complete(service, StartRequest(task_id="T", mode="assess", base_run_id=run["run_id"], max_assessments=1))
    assert sum(a["priority"] != "unassessed" for a in run["result"]["annotations"].values()) >= 5
