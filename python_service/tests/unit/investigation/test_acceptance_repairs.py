"""Regressions observed in the PC.E01 acceptance run."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from httpserver.services.evidence.exceptions import EvidenceNotFoundError
from httpserver.services.investigation import InvestigationRepository
from httpserver.services.investigation.notes import read_note, save_note
from httpserver.services.investigation.prompts import (
    CURRENT_PROMPT_VERSION, PROMPT_REGISTRY, CHINESE_OUTPUT_RULE,
    SECONDARY_ANALYSIS_SYSTEM_V3, SECONDARY_ANALYSIS_USER_TEMPLATE_V3,
    _format_snapshot_text,
)
from test_investigation_repository import _make_files_db, _file_resolved


def test_optional_git_metadata_failure_does_not_abort_package(monkeypatch):
    import subprocess
    from httpserver.services import android_field_package as package
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("git", 10)
    monkeypatch.setattr(package.subprocess, "run", timeout)
    assert package._commit() is None
    assert package._git_output("status", "--porcelain") is None


def test_notes_are_versioned_context_and_task_isolated(tmp_path):
    fdb, idb = tmp_path / "files.db", tmp_path / "investigation.db"
    _make_files_db(str(fdb), [{"path": "/case/report.docx", "llm_description": "original"}])
    repo = InvestigationRepository(str(idb), "A")
    original = repo.capture_if_absent(_file_resolved(str(fdb)))
    key = "file:/case/report.docx"
    assert read_note(idb, "A", "evidence", key) is None
    with sqlite3.connect(idb) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='investigation_analyst_notes'").fetchone()
    first = save_note(repo, "evidence", key, "调查方向", "analyst")
    second = save_note(repo, "evidence", key, "补充背景", "analyst")
    assert (first["version"], second["version"]) == (1, 2)
    assert read_note(idb, "A", "evidence", key) == second
    assert read_note(idb, "B", "evidence", key) is None
    assert repo.capture_if_absent(_file_resolved(str(fdb))) == original
    with pytest.raises(EvidenceNotFoundError):
        save_note(repo, "evidence", "file:/missing", "x", "analyst")
    with ThreadPoolExecutor(max_workers=4) as pool:
        notes = list(pool.map(lambda i: save_note(repo, "evidence", key, str(i), "analyst"), range(4)))
    assert sorted(n["version"] for n in notes) == [3, 4, 5, 6]


def test_read_note_does_not_create_store(tmp_path):
    missing = tmp_path / "absent" / "investigation.db"
    assert read_note(missing, "A", "evidence", "file:/a") is None
    assert not missing.parent.exists()


def test_v7_uses_exact_utc_and_does_not_rewrite_historical_prompt():
    payload = {"mtime": 1712926716, "ctime": 1747386786}
    snap = {"evidence_type": "file", "evidence_key": "file:/a", "payload": payload}
    env = SimpleNamespace(evidence_snapshot=snap, prompt_version=CURRENT_PROMPT_VERSION)
    text = _format_snapshot_text(env)[2]
    assert "修改时间: 2024-04-12T12:58:36Z" in text
    assert "元数据变更时间: 2025-05-16T09:13:06Z" in text
    assert "创建时间:" not in text
    env.prompt_version = "investigation-evidence-analysis:v5"
    assert "创建时间: 1747386786" in _format_snapshot_text(env)[2]
    assert PROMPT_REGISTRY[env.prompt_version] == (
        SECONDARY_ANALYSIS_SYSTEM_V3 + CHINESE_OUTPUT_RULE, SECONDARY_ANALYSIS_USER_TEMPLATE_V3)


def test_graph_display_budget_keeps_real_links_and_focus():
    from httpserver.services.event_graph.snapshot import projection
    from httpserver.services.event_graph.models import ViewFilter
    snapshot = {
        "nodes": [
            *({"id": f"event:{i}", "kind": "event", "name": str(i)} for i in range(300)),
            *({"id": f"evidence:{i}", "kind": "evidence", "name": f"file{i}"} for i in range(300)),
        ],
        "links": [{"id": str(i), "source": f"event:{i}", "target": f"evidence:{i}",
                   "kind": "event_evidence", "label": "佐证"} for i in range(300)],
        "events": [], "coverage": {}, "policy_version": "test",
    }
    result = projection(snapshot, ViewFilter(max_nodes=200))
    assert len(result["nodes"]) == 200
    assert len(result["links"]) == 100
    assert result["matched_links"] == 300
    assert result["display_truncated"]
    focused = projection(snapshot, ViewFilter(max_nodes=2, focus_id="evidence:250"))
    assert {n["id"] for n in focused["nodes"]} == {"event:250", "evidence:250"}
