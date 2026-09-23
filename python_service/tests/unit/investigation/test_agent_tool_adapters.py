"""P3-2 read-only adapter tests (work order §54) against fake service facades."""

from types import SimpleNamespace
from typing import Any, Optional

import pytest
from pydantic import BaseModel, ConfigDict

from httpserver.services.investigation.agent_tools.adapters import (
    build_read_only_registry,
)
from httpserver.services.investigation.agent_tools.adapters.base import (
    ToolCatalogConfig,
)
from httpserver.services.investigation.agent_tools.adapters.services import (
    ForensicToolServices,
)
from httpserver.services.investigation.agent_tools.context import (
    ForensicToolContext,
)
from httpserver.services.investigation.agent_tools.errors import (
    ToolErrorCode,
    ToolExecutionError,
)
from httpserver.services.investigation.agent_tools.definitions import (
    ToolAccess,
)
from httpserver.services.investigation.agent_tools.registry import (
    ToolExecutionOutcome,
)
from httpserver.services.investigation.models import EvidenceSummary


FORBIDDEN_SCHEMA_FIELDS = (
    "task_id",
    "investigation_id",
    "run_id",
    "db_path",
    "database_path",
    "sql",
    "filesystem_root",
    "service",
)


# ---------------------------------------------------------------------------
# fake facades
# ---------------------------------------------------------------------------


class FakeCppBackend:
    def __init__(self):
        self.files = {"files": [_file_row("C/Users/tea/x.doc"), _file_row("D/odd.txt")], "total_count": 2}
        self.events = {
            "events": [
                {"id": 1, "event_type": "FILE_CREATED", "file_path": "C/x.doc",
                 "timestamp": 1690000123, "description": "created"},
                {"id": 2, "event_type": "USB_DEVICE", "file_path": None,
                 "timestamp": 1690000000, "description": "usb in"},
            ],
            "total_count": 2,
        }

    async def get_task(self, task_id, **kwargs):
        return {"id": task_id, "image_name": "disk.E01", "status": "done",
                "scenarios": ["windows"], "scenario_databases": {"windows": "/db/windows.db"},
                "output_files_db": "/db/files.db", "output_events_db": "/db/events.db"}

    async def get_task_files_paginated(self, task_id, **kwargs):
        return self.files

    async def get_task_events(self, task_id, **kwargs):
        return self.events


def _file_row(path: str) -> dict[str, Any]:
    return {
        "path": path,
        "name": path.rsplit("/", 1)[-1],
        "extension": path.rsplit(".", 1)[-1],
        "size": 100,
        "md5": "deadbeef",
        "is_deleted": 0,
        "modified_time": 1690000000,
        "llm_description": "a document",
    }


class FakeInvestigationService:
    def __init__(self, resolved: Optional[dict[str, Any]]):
        self.resolved = resolved

    async def resolve_evidence(self, task_id, evidence_key):
        return self.resolved

    async def effective_event_claims(self, task_id, event_id):
        if event_id == "missing":
            raise KeyError(event_id)
        return [
            {"id": "c1", "claim_type": "FACT", "claim_text": "file existed",
             "grounding_status": "grounded", "status": "accepted",
             "evidence_refs": ["file:C/x.doc"]},
        ]


class FakeReadService:
    def __init__(self, summaries):
        self.summaries = summaries

    async def list_evidence(self, task_id):
        return self.summaries

    async def list_analysis_claims(self, task_id, analysis_id):
        if analysis_id == "ghost":
            return None
        return [
            SimpleNamespace(
                claim_id="ac1",
                claim_type="INFERENCE",
                claim_text="actor staged files",
                grounding_status="partially_grounded",
                evidence_refs=("file:C/x.doc",),
            )
        ]


class FakeExecutor:
    async def list_analyses(self, task_id, evidence_key):
        return [_analysis("a-1", evidence_key, "accepted"), _analysis("a-2", evidence_key, "rejected")]

    async def list_all_analyses(self, task_id):
        return {
            "file:C/x.doc": [_analysis("a-1", "file:C/x.doc", "accepted")],
            "cluster:v1:1690000020:USB_DEVICE": [
                _analysis("a-3", "cluster:v1:1690000020:USB_DEVICE", "failed")
            ],
        }


def _analysis(analysis_id: str, evidence_key: str, status: str):
    return SimpleNamespace(
        analysis_id=analysis_id,
        evidence_key=evidence_key,
        version=1,
        status=status,
        grounding_status="grounded" if status == "accepted" else None,
        summary=f"summary {analysis_id}",
        description=None,
        created_at="2026-09-23T00:00:00",
        decision_reason="ok" if status == "accepted" else "bad",
    )


def make_services(**overrides) -> ForensicToolServices:
    fields = dict(
        cpp_backend=FakeCppBackend(),
        investigation_service=FakeInvestigationService(
            {
                "evidence_key": "file:C/Users/tea/x.doc",
                "evidence_type": "file",
                "title": "x.doc",
                "timestamp": 1690000000,
                "start_time": 1690000000,
                "end_time": None,
                "metadata": {"author": "tea"},
                "content": "PRECIOUS CONTENT " * 10,
                "md5": "deadbeef",
                "size": 100,
                "extension": "doc",
                "is_deleted": 0,
                "related_evidence_keys": ["file:C/Users/tea/y.doc"],
                "initial_summary": "summary",
                "initial_description": "description",
            }
        ),
        investigation_read_service=FakeReadService(
            [
                EvidenceSummary(
                    task_id="task-A",
                    evidence_key="cluster:v1:1690000020:USB_DEVICE",
                    evidence_type="cluster",
                    captured_at=1690000123,
                ),
                EvidenceSummary(
                    task_id="task-A",
                    evidence_key="file:C/Users/tea/x.doc",
                    evidence_type="file",
                    captured_at=1690000100,
                ),
            ]
        ),
        investigation_event_service=SimpleNamespace(list_events=None),
        secondary_analysis_executor=FakeExecutor(),
    )
    fields.update(overrides)
    return ForensicToolServices(**fields)


def make_context() -> ForensicToolContext:
    return ForensicToolContext(
        task_id="task-A",
        investigation_id="inv-A",
        run_id="run-A",
        source_scope_ids=("windows",),
        allowed_tool_ids=frozenset(
            {
                "get_task_context",
                "query_platform_artifacts",
                "search_evidence",
                "get_evidence",
                "find_related_evidence",
                "search_files",
                "search_timeline",
                "find_temporal_neighbors",
                "get_existing_analyses",
                "get_existing_claims",
            }
        ),
    )


# ---------------------------------------------------------------------------
# catalog-wide audits (P3-E8, P3-E9, §53)
# ---------------------------------------------------------------------------


def test_catalog_registers_only_read_tools():
    registry = build_read_only_registry(make_services())
    assert len(registry) == 10
    assert all(d.access == ToolAccess.READ for d in registry.iter_definitions())


def test_catalog_schema_audit_no_identity_or_infrastructure_fields():
    registry = build_read_only_registry(make_services())
    for definition in registry.iter_definitions():
        properties = definition.input_json_schema().get("properties", {})
        for forbidden in FORBIDDEN_SCHEMA_FIELDS:
            assert forbidden not in properties, (definition.tool_id, forbidden)


def test_no_sql_or_raw_db_tool_names_registered():
    registry = build_read_only_registry(make_services())
    names = {d.tool_id for d in registry.iter_definitions()}
    assert not names & {"execute_sql", "query_sql", "raw_database_query"}


# ---------------------------------------------------------------------------
# evidence discovery / hydration (P3-E10)
# ---------------------------------------------------------------------------


async def test_search_evidence_returns_sorted_digest_page():
    registry = build_read_only_registry(make_services())
    result = await registry.execute(make_context(), "search_evidence", {})
    items = result["data"]["items"]
    keys = [item["evidence_key"] for item in items]
    assert keys == sorted(keys)
    assert result["evidence_refs"] == keys
    assert result["data"]["continuation"] is None


async def test_search_evidence_pagination_stable():
    registry = build_read_only_registry(make_services(), config=ToolCatalogConfig(default_page_size=1))
    context = make_context()
    page1 = await registry.execute(context, "search_evidence", {"page_size": 1})
    page2 = await registry.execute(
        context,
        "search_evidence",
        {"page_size": 1, "page_token": int(page1["data"]["continuation"])},
    )
    combined = [i["evidence_key"] for i in page1["data"]["items"]] + [
        i["evidence_key"] for i in page2["data"]["items"]
    ]
    assert combined == sorted(
        [
            "cluster:v1:1690000020:USB_DEVICE",
            "file:C/Users/tea/x.doc",
        ]
    )
    assert page2["data"]["continuation"] is None


async def test_get_evidence_hydration_levels():
    registry = build_read_only_registry(make_services())
    digest = await registry.execute(
        make_context(), "get_evidence", {"evidence_key": "file:C/Users/tea/x.doc"}
    )
    assert digest["data"]["content_preview"] is None
    assert digest["data"]["title"] == "x.doc"
    preview = await registry.execute(
        make_context(),
        "get_evidence",
        {"evidence_key": "file:C/Users/tea/x.doc", "hydration_level": "preview"},
    )
    assert "PRECIOUS CONTENT" in preview["data"]["content_preview"]
    assert digest["evidence_refs"] == ["file:C/Users/tea/x.doc"]


async def test_get_evidence_malformed_key_fails_closed():
    registry = build_read_only_registry(make_services())
    with pytest.raises(ToolExecutionError) as excinfo:
        await registry.execute(
            make_context(), "get_evidence", {"evidence_key": "garbage"}
        )
    assert excinfo.value.code == ToolErrorCode.EVIDENCE_REF_INVALID


async def test_get_evidence_wrong_task_is_opaque_failure():
    services = make_services(
        investigation_service=FakeInvestigationService(None)
    )
    registry = build_read_only_registry(services)
    with pytest.raises(ToolExecutionError) as excinfo:
        await registry.execute(
            make_context(), "get_evidence", {"evidence_key": "file:C/elsewhere.txt"}
        )
    assert excinfo.value.code == ToolErrorCode.EVIDENCE_REF_INVALID
    # no internal layout in the message
    assert "/db/" not in str(excinfo.value)


async def test_find_related_evidence_cluster_members():
    registry = build_read_only_registry(make_services())
    result = await registry.execute(
        make_context(), "find_related_evidence", {"evidence_key": "file:C/Users/tea/x.doc"}
    )
    assert result["data"]["related_evidence_keys"] == ("file:C/Users/tea/y.doc",)
    assert result["evidence_refs"][0] == "file:C/Users/tea/x.doc"


# ---------------------------------------------------------------------------
# files / timeline (P3-E10)
# ---------------------------------------------------------------------------


async def test_search_files_returns_evidence_keys():
    registry = build_read_only_registry(make_services())
    result = await registry.execute(make_context(), "search_files", {})
    keys = [item["evidence_key"] for item in result["data"]["items"]]
    assert keys == ["file:C/Users/tea/x.doc", "file:D/odd.txt"]
    assert result["evidence_refs"] == keys


async def test_search_timeline_derives_cluster_keys_server_side():
    registry = build_read_only_registry(make_services())
    result = await registry.execute(make_context(), "search_timeline", {})
    clusters = [i["cluster_evidence_key"] for i in result["data"]["items"]]
    assert "cluster:v1:28166668:FILE_CREATED" in clusters
    assert all(c is not None for c in clusters)


async def test_timeline_tool_accepts_no_db_path_args():
    registry = build_read_only_registry(make_services())
    definition = registry.resolve_definition("search_timeline")
    assert "db_path" not in definition.input_json_schema().get("properties", {})


async def test_find_temporal_neighbors_anchor_from_evidence_and_window_bound():
    registry = build_read_only_registry(make_services())
    result = await registry.execute(
        make_context(),
        "find_temporal_neighbors",
        {
            "anchor_evidence_key": "file:C/Users/tea/x.doc",
            "window_seconds": 10**9,
        },
    )
    data = result["data"]
    assert data["anchor_timestamp"] == 1690000000
    assert data["window_seconds"] == ToolCatalogConfig().max_temporal_window_seconds
    assert data["result_count"] == 2


# ---------------------------------------------------------------------------
# investigation reads (§20)
# ---------------------------------------------------------------------------


async def test_existing_analyses_keep_faithful_review_state():
    registry = build_read_only_registry(make_services())
    result = await registry.execute(
        make_context(), "get_existing_analyses", {"evidence_key": "file:C/x.doc"}
    )
    statuses = {item["analysis_id"]: item["status"] for item in result["data"]["items"]}
    assert statuses == {"a-1": "accepted", "a-2": "rejected"}


async def test_existing_claims_event_and_analysis_paths():
    registry = build_read_only_registry(make_services())
    event_claims = await registry.execute(
        make_context(), "get_existing_claims", {"event_id": "e-1"}
    )
    assert event_claims["data"]["items"][0]["status"] == "accepted"
    assert event_claims["data"]["items"][0]["evidence_refs"] == ("file:C/x.doc",)
    analysis_claims = await registry.execute(
        make_context(), "get_existing_claims", {"analysis_id": "a-1"}
    )
    assert analysis_claims["data"]["items"][0]["grounding_status"] == "partially_grounded"
    with pytest.raises(ToolExecutionError) as excinfo:
        await registry.execute(
            make_context(), "get_existing_claims", {"event_id": "missing"}
        )
    assert excinfo.value.code == ToolErrorCode.TOOL_INPUT_INVALID


async def test_get_task_context_digest_without_paths():
    registry = build_read_only_registry(make_services())
    result = await registry.execute(make_context(), "get_task_context", {})
    data = result["data"]
    assert data["platforms"] == ("windows",)
    assert data["source_scopes"][0]["database_kinds"] == ("events", "files", "windows")
    serialized = str(data)
    assert "/db/windows.db" not in serialized
    assert "output_files_db" not in serialized
