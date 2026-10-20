"""Quiesced synthetic application backup/restore; never opens a real Task."""

import hashlib
import importlib.util
import json
import shutil
import sqlite3
from pathlib import Path

from httpserver.services.android_field_package import _snapshot, verify_package
from httpserver.services.android_result_sets import read_frozen_artifact
from httpserver.services.forensic_report.generation import ReportGenerationInputBuilder
from httpserver.services.forensic_report.narrative_reader import read_narrative_version_strict
from httpserver.services.investigation.graph_reader import InvestigationGraphReader
from httpserver.services.investigation.repository import InvestigationRepository


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_6b_fixture():
    path = Path(__file__).resolve().parents[1] / "unit/investigation/test_android_artifact_report_chain.py"
    spec = importlib.util.spec_from_file_location("synthetic_6b_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.test_selected_sms_freeze_review_report_and_exact_backlink


def test_quiesced_backup_restores_v7_v8_r2_result_set_and_partial_html(tmp_path):
    from sys import path as sys_path
    sys_path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
    from isolated_target import require_private_loopback_namespace
    require_private_loopback_namespace()

    source = tmp_path / "source"
    source.mkdir()
    _load_6b_fixture()(source)  # synthetic Android row, accepted analysis, R2 and package

    old = source / "old-task"
    old.mkdir()
    old_db = old / "investigation.db"
    old_repo = InvestigationRepository.__new__(InvestigationRepository)
    old_repo.db_path, old_repo.task_id, old_repo.existing_only = old_db, "old-task", False
    old_repo._initialize_v7_atomically()
    with sqlite3.connect(old_db) as con:
        con.execute("INSERT INTO evidence_snapshots(task_id,evidence_key,evidence_type,normalized_path,snapshot_json,captured_at) VALUES(?,?,?,?,?,?)",
                    ("old-task", "file:/old.txt", "file", "/old.txt",
                     '{"evidence_type":"file","normalized_path":"/old.txt"}', 1))

    html = source / "external-html"
    html.mkdir()
    html_db = html / "records.db"
    with sqlite3.connect(html_db) as con:
        con.execute("CREATE TABLE records(id INTEGER PRIMARY KEY,source_type TEXT,content TEXT)")
        con.execute("INSERT INTO records VALUES(1,'external_html_report','synthetic only')")
    (html / "report_manifest.json").write_text(
        json.dumps({"status": "PARTIAL", "missing_attachments": 1}), encoding="utf-8")

    selected = json.loads((source / "delivery/selected_android_evidence.json").read_text())
    key = selected[0]["evidence_key"]
    result_set_id = selected[0]["snapshot"]["result_set_id"]
    report_db = source / "reports/reports.db"
    with sqlite3.connect(report_db) as con:
        report_id = con.execute("SELECT report_id FROM report_versions WHERE report_kind='llm_generation'").fetchone()[0]

    # Writers have finished before the backup epoch; no independent DB copies
    # are claimed to be atomic while writes are active.
    databases = ("android.db", "investigation.db", "reports/reports.db",
                 "old-task/investigation.db", "external-html/records.db")
    before = {name: _sha(source / name) for name in databases}
    backup = tmp_path / "backup"
    backup.mkdir()
    for name in databases:
        target = backup / name
        target.parent.mkdir(parents=True, exist_ok=True)
        _snapshot(source / name, target)
    for relative in ("android_result_sets", "reports/snapshots", "delivery"):
        shutil.copytree(source / relative, backup / relative)
    shutil.copy2(html / "report_manifest.json", backup / "external-html/report_manifest.json")
    after = {name: _sha(source / name) for name in databases}
    assert before == after
    assert all(sqlite3.connect(backup / name).execute("PRAGMA integrity_check").fetchone()[0] == "ok"
               for name in databases)

    restored = tmp_path / "restored"
    shutil.copytree(backup, restored)
    task = {"id": "synthetic-android-task", "output_files_db": str(restored / "android.db"),
            "android_source": "dir"}
    frozen = read_frozen_artifact(task, result_set_id, "sms", 1)
    assert frozen["record"]["body"] == "同一条短信"
    reader = InvestigationGraphReader(restored / "investigation.db", task["id"])
    assert reader.latest_snapshot(key).payload.result_set_id == result_set_id
    envelope = ReportGenerationInputBuilder(restored / "investigation.db", task["id"]).assemble("final-report:v3")
    assert envelope.schema_version == 3 and envelope.allowed_report_evidence_ids == (key,)
    version, narrative = read_narrative_version_strict(
        restored / "reports/reports.db", restored / "reports", task["id"], report_id)
    assert version.status == "ready"
    assert narrative.citations[0].evidence_key == key
    assert verify_package(restored / "delivery")["valid"] is True
    old_hash = _sha(restored / "old-task/investigation.db")
    assert InvestigationGraphReader(restored / "old-task/investigation.db", "old-task").latest_snapshot(
        "file:/old.txt").payload.normalized_path == "/old.txt"
    assert _sha(restored / "old-task/investigation.db") == old_hash
    assert sqlite3.connect(restored / "old-task/investigation.db").execute("PRAGMA user_version").fetchone()[0] == 7
    with sqlite3.connect(restored / "external-html/records.db") as con:
        assert con.execute("SELECT source_type FROM records").fetchone()[0] == "external_html_report"
    assert json.loads((restored / "external-html/report_manifest.json").read_text())["status"] == "PARTIAL"
