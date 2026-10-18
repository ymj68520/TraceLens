"""Synthetic, explicitly selected Android row through frozen R2 citation.

This does not represent a real model run or real-image compatibility.
"""

import asyncio
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from httpserver.services.android_artifact_reader import artifact_detail
from httpserver.services.android_result_sets import freeze_selected_result, read_frozen_artifact
from httpserver.services.android_field_package import build_package, verify_package
from httpserver.services.evidence.resolver import EvidenceResolver
from httpserver.services.evidence.exceptions import EvidenceNotFoundError
from httpserver.services.investigation.repository import SUPPORTED_SCHEMA_VERSION
from httpserver.services.forensic_report.generation import ReportGenerationAdmissionService, ReportGenerationInputBuilder
from httpserver.services.forensic_report.generation_execution import (
    ReportCitationInvalidError, ReportGenerationExecutor, build_citation_manifest, validate_report_citations,
)
from httpserver.services.forensic_report.generation_writer import GenerationReportWriter
from httpserver.services.forensic_report.narrative_reader import read_narrative_version_strict
from httpserver.services.forensic_report.repository import ReportRepository
from httpserver.services.forensic_report.models import StructuredReportResponse, parse_generation_envelope
from httpserver.services.investigation.models import (
    AnalysisReviewDecision, ClaimCandidate, SecondaryAnalysisStatus, parse_analysis_input_envelope,
)
from httpserver.services.investigation.repository import AnalysisBindingConflictError, InvestigationRepository
from httpserver.services.investigation.graph_reader import InvestigationGraphReader
from httpserver.services.investigation.execution import SecondaryAnalysisExecutor
from httpserver.services.investigation.service import InvestigationCaptureService
from httpserver.services.investigation.review import InvestigationReviewService


def test_selected_sms_freeze_review_report_and_exact_backlink(tmp_path):
    task_id = "synthetic-android-task"
    db = tmp_path / "android.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE sms_messages(id INTEGER PRIMARY KEY,address TEXT,body TEXT,date INTEGER,type INTEGER)")
        con.execute("INSERT INTO sms_messages VALUES(1,'10086','同一条短信',1700000000000,1)")
        con.execute("INSERT INTO sms_messages VALUES(2,'10086','同一条短信',1700000000000,1)")
        con.execute("CREATE TABLE android_source_coverage(artifact_kind TEXT,source_path TEXT,status TEXT,detail TEXT)")
        con.execute("INSERT INTO android_source_coverage VALUES('sms','data/data/telephony/mmssms.db','parsed','candidate bundle')")
    task = {"id": task_id, "output_files_db": str(db), "android_source": "dir"}
    detail = artifact_detail(task, "sms", 1)
    result = freeze_selected_result(task, "sms", 1, expected_row_hash=detail["record_hash"],
                                    expected_source_revision=detail["source_revision"])
    key = f"android_artifact:v1:{task_id}:{result['result_set_id']}:sms:1"
    cpp = AsyncMock()
    cpp.get_task = AsyncMock(return_value=task)
    resolved = asyncio.run(EvidenceResolver(cpp).resolve_evidence(task_id, key))
    repo = InvestigationRepository(tmp_path / "investigation.db", task_id)
    snapshot = repo.capture_if_absent(resolved)
    assert snapshot.payload.record_fields == {
        "id": 1, "address": "10086", "body": "同一条短信",
        "date": 1700000000000, "type": 1,
    }
    assert snapshot.payload.raw_timestamp == 1700000000000
    assert snapshot.payload.provenance["original_primary_key"] is None
    assert snapshot.payload.provenance["input_file"] == "candidate_only"
    assert snapshot.payload.timestamp_unit is None
    assert repo.capture_if_absent(resolved).snapshot_id == snapshot.snapshot_id
    analysis_prompt_calls = []

    class AnalysisLLM:
        async def chat_completion(self, system, user):
            analysis_prompt_calls.append(user)
            return {"model": "test-only-mock", "content": json.dumps({
                "description": "合成测试分析", "summary": "合成测试摘要",
                "claims": [{"claim_type": "FACT", "claim_text": "冻结记录包含一条短信", "evidence_refs": [key]}],
            }, ensure_ascii=False)}

    async def run_analysis():
        capture_service = InvestigationCaptureService(cpp, EvidenceResolver(cpp))
        executor = SecondaryAnalysisExecutor(cpp, AnalysisLLM(), capture_service)
        submitted = await executor.submit(task_id, key)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = repo.get_analysis(submitted.analysis_id)
            if current.status in (SecondaryAnalysisStatus.review_pending, SecondaryAnalysisStatus.failed):
                await executor.shutdown()
                return current
            await asyncio.sleep(.01)
        raise AssertionError("synthetic analysis did not finish")

    analysis = asyncio.run(run_analysis())
    assert analysis.status == SecondaryAnalysisStatus.review_pending, analysis.error_message
    frozen_input = parse_analysis_input_envelope(analysis.input_envelope_json)
    assert frozen_input.schema_version == 3
    assert frozen_input.evidence_snapshot["evidence_key"] == key
    assert len(analysis_prompt_calls) == 1 and ":sms:2" not in analysis_prompt_calls[0]
    reviewed = asyncio.run(InvestigationReviewService(cpp).review(
        task_id, analysis.analysis_id, decision=AnalysisReviewDecision.accepted,
        reviewer="synthetic-principal"))
    assert reviewed.status == SecondaryAnalysisStatus.accepted
    assert reviewed.decided_by == "synthetic-principal"
    assert repo.get_snapshot(key).payload.provenance["input_file"] == "candidate_only"
    repo.add_report_evidence(key, report_status="main", analysis_id=analysis.analysis_id,
                             added_by="synthetic-principal")
    envelope = ReportGenerationInputBuilder(tmp_path / "investigation.db", task_id).assemble()
    assert envelope.schema_version == 3 and envelope.prompt_version == "final-report:v3"
    assert envelope.allowed_report_evidence_ids == (key,)
    parsed = parse_generation_envelope(json.dumps(envelope.model_dump(mode="json")))
    assert parsed.main_evidence[0].snapshot.payload.record_fields["body"] == "同一条短信"
    assert parsed.main_evidence[0].snapshot.payload.record_fields["address"] == "10086"
    assert parsed.main_evidence[0].snapshot.payload.record_fields["type"] == 1
    response = StructuredReportResponse.model_validate({
        "title": "合成报告", "sections": [{"heading": "短信", "content": "该记录含短信。", "citation_ids": ["c001"]}],
        "citations": [{"citation_id": "c001", "evidence_key": key, "analysis_id": analysis.analysis_id}],
    })
    validate_report_citations(response, parsed)
    citation = build_citation_manifest(response, parsed)[0]
    assert citation.evidence_key == key and citation.analysis_id == analysis.analysis_id
    assert read_frozen_artifact(task, result["result_set_id"], "sms", 1)["record"]["body"] == "同一条短信"
    report_root = tmp_path / "reports"
    report_root.mkdir()

    class ReportLLM:
        def __init__(self):
            self.calls = []

        async def chat_completion(self, system, user):
            self.calls.append(user)
            responses = [
                {"title": "合成报告", "sections": [
                    {"heading": "案件背景与检材概况", "brief": "合成", "group_ids": []},
                    {"heading": "短信证据", "brief": "单条短信", "group_ids": ["android_records"]},
                    {"heading": "综合结论", "brief": "范围", "group_ids": []}]},
                {"heading": "案件背景与检材概况", "content": "仅使用合成数据。", "citations": []},
                {"heading": "短信证据", "content": "选中的冻结短信正文为同一条短信。", "citations": [
                    {"citation_id": "c001", "evidence_key": key, "analysis_id": analysis.analysis_id}]},
                {"heading": "综合结论", "content": "原始数据库行尚未核实。", "citations": []},
            ]
            return {"model": "test-only-mock", "content": json.dumps(responses[len(self.calls) - 1], ensure_ascii=False)}

    report_llm = ReportLLM()
    report_repo = ReportRepository(report_root / "reports.db")

    async def run_report():
        admission = ReportGenerationAdmissionService(cpp, report_repo)
        executor = ReportGenerationExecutor(report_repo, GenerationReportWriter(report_root), report_llm)
        row = await admission.admit(task_id, requested_by="synthetic-principal")
        await executor.submit(row.generation_id)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = report_repo.get_generation_input(row.generation_id)
            if current.status in ("completed", "failed"):
                await executor.shutdown()
                return current
            await asyncio.sleep(.01)
        raise AssertionError("synthetic report did not finish")

    generated = asyncio.run(run_report())
    assert generated.status == "completed", generated.error_message
    assert len(report_llm.calls) == 4
    assert ":sms:2" not in "\n".join(report_llm.calls)
    report_id = generated.report_id
    published = read_narrative_version_strict(report_root / "reports.db", report_root, task_id, report_id)
    assert published is not None
    version, narrative = published
    assert narrative.citations[0].evidence_key == key
    assert narrative.citations[0].citation_id == "c001"
    assert narrative.citations[0].analysis_id == analysis.analysis_id
    delivery = tmp_path / "delivery"
    manifest = build_package(output=delivery, task=task, report_root=report_root)
    assert "selected_android_evidence.json" in manifest["files"]
    selected = json.loads((delivery / "selected_android_evidence.json").read_text())
    assert len(selected) == 1 and selected[0]["evidence_key"] == key
    assert selected[0]["frozen_record"]["body"] == "同一条短信"
    assert selected[0]["bound_analysis_id"] == analysis.analysis_id
    assert selected[0]["snapshot"]["provenance"]["input_file"] == "candidate_only"
    assert selected[0]["bound_analysis"]["decided_by"] == "synthetic-principal"
    packaged_citations = json.loads((delivery / "selected_android_citations.json").read_text())
    assert packaged_citations[0]["report_id"] == report_id
    assert packaged_citations[0]["citation_id"] == "c001"
    assert packaged_citations[0]["analysis_id"] == analysis.analysis_id
    assert verify_package(delivery)["valid"] is True
    assert f"android-result-{result['result_set_id']}.db" in manifest["files"]
    with sqlite3.connect(db) as con:
        con.execute("UPDATE sms_messages SET body='newer dynamic result' WHERE id=1")
    assert verify_package(delivery)["valid"] is True  # offline frozen copy remains valid
    print("SYNTHETIC_6B_IDS=" + json.dumps({
        "task_id": task_id, "result_set_id": result["result_set_id"], "evidence_key": key,
        "snapshot_id": snapshot.snapshot_id, "analysis_id": analysis.analysis_id,
        "review_status": reviewed.status.value, "report_id": report_id, "citation_id": "c001",
        "test_only_model": True,
    }))
    with pytest.raises(ReportCitationInvalidError):
        bad = response.model_copy(update={"citations": (
            response.citations[0].model_copy(update={"evidence_key": key.replace(":1", ":2")}),)})
        validate_report_citations(bad, parsed)
    with pytest.raises(ReportCitationInvalidError):
        bad_analysis = response.model_copy(update={"citations": (
            response.citations[0].model_copy(update={"analysis_id": "sa_wrong"}),)})
        validate_report_citations(bad_analysis, parsed)


def test_v7_migration_keeps_existing_ids_and_fk(tmp_path):
    db = tmp_path / "investigation.db"
    # Construct exactly the released v7 DDL in an isolated synthetic DB.
    from httpserver.services.investigation.repository import _CREATE_EVIDENCE_SNAPSHOTS_SQL
    with sqlite3.connect(db) as con:
        con.execute(_CREATE_EVIDENCE_SNAPSHOTS_SQL)
        con.execute("INSERT INTO evidence_snapshots(task_id,evidence_key,evidence_type,normalized_path,snapshot_json,captured_at) VALUES(?,?,?,?,?,?)",
                    ("t", "file:/old", "file", "/old", '{"evidence_type":"file","normalized_path":"/old"}', 1))
        con.execute("CREATE TABLE old_child(snapshot_id INTEGER REFERENCES evidence_snapshots(id))")
        con.execute("INSERT INTO old_child VALUES(1)")
        con.execute("PRAGMA user_version=7")
    # Migration helper itself is tested here; repository validation requires the full released schema.
    repo = InvestigationRepository.__new__(InvestigationRepository)
    repo.db_path, repo.task_id, repo.existing_only = db, "t", False
    repo._migrate_v7_to_v8()
    with sqlite3.connect(db) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 8
        assert con.execute("SELECT id,evidence_key,snapshot_json FROM evidence_snapshots").fetchone() == (
            1, "file:/old", '{"evidence_type":"file","normalized_path":"/old"}')
        assert not con.execute("PRAGMA foreign_key_check").fetchall()
        assert con.execute("SELECT * FROM old_child").fetchone() == (1,)
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("UPDATE evidence_snapshots SET captured_at=2 WHERE id=1")


def test_full_v7_report_binding_survives_v8_rebuild(tmp_path):
    db = tmp_path / "investigation.db"
    repo = InvestigationRepository.__new__(InvestigationRepository)
    repo.db_path, repo.task_id, repo.existing_only = db, "old-task", False
    repo._initialize_v7_atomically()
    assert sqlite3.connect(db).execute("PRAGMA user_version").fetchone()[0] == 7
    payload = '{"evidence_type":"file","normalized_path":"/old.txt","initial_summary":"old"}'
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO evidence_snapshots(task_id,evidence_key,evidence_type,normalized_path,snapshot_json,captured_at) VALUES(?,?,?,?,?,?)",
                    ("old-task", "file:/old.txt", "file", "/old.txt", payload, 7))
    snapshot = repo.get_snapshot("file:/old.txt")
    analysis = repo.create_analysis(snapshot, prompt_version="investigation-evidence-analysis:v3")
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    repo.complete_analysis_for_review(analysis.analysis_id, description="old", summary="old", model="test-only-mock",
                                     candidates=[ClaimCandidate(claim_type="FACT", claim_text="old", evidence_refs=("file:/old.txt",))])
    repo.review_analysis(analysis.analysis_id, decision=AnalysisReviewDecision.accepted, reviewer="old-reviewer")
    repo.add_report_evidence("file:/old.txt", report_status="main", analysis_id=analysis.analysis_id, added_by="old-reviewer")
    before = db.read_bytes()
    assert InvestigationGraphReader(db, "old-task").latest_snapshot("file:/old.txt").snapshot_id == snapshot.snapshot_id
    old_input = ReportGenerationInputBuilder(db, "old-task").assemble()
    assert old_input.schema_version == 2
    assert hashlib.sha256(db.read_bytes()).digest() == hashlib.sha256(before).digest()
    repo._migrate_v7_to_v8()
    reopened = InvestigationRepository(db, "old-task")
    after_input = ReportGenerationInputBuilder(db, "old-task").assemble()
    assert after_input.model_dump(mode="json") == old_input.model_dump(mode="json")
    assert reopened.get_snapshot("file:/old.txt").snapshot_id == snapshot.snapshot_id
    assert reopened.get_analysis(analysis.analysis_id).input_hash == analysis.input_hash
    with sqlite3.connect(db) as con:
        con.execute("PRAGMA foreign_keys=ON")
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("DELETE FROM evidence_snapshots WHERE id=?", (snapshot.snapshot_id,))
    assert before != db.read_bytes()  # only this isolated synthetic DB was migrated


@pytest.mark.parametrize("kind,ddl,inserted,expected_field,expected_value", [
    ("sms", "CREATE TABLE sms_messages(id INTEGER PRIMARY KEY,address TEXT,body TEXT,date INTEGER,type INTEGER)",
     (1, "10086", "同文", 1700000000000, 1), "body", "同文"),
    ("contacts", "CREATE TABLE contacts(id INTEGER PRIMARY KEY,display_name TEXT,phone_number TEXT,email TEXT)",
     (1, "合成联系人", "12345", None), "display_name", "合成联系人"),
    ("apps", "CREATE TABLE installed_packages(id INTEGER PRIMARY KEY,package_name TEXT,version TEXT,installer TEXT)",
     (1, "com.example.synthetic", "1.2", None), "package_name", "com.example.synthetic"),
    ("wifi", "CREATE TABLE wifi_networks(id INTEGER PRIMARY KEY,ssid TEXT,key_mgmt TEXT,pre_shared_key TEXT)",
     (1, "SyntheticWifi", "WPA2", "synthetic-secret"), "ssid", "SyntheticWifi"),
])
def test_four_artifact_kinds_share_one_frozen_identity_adapter(
    tmp_path, kind, ddl, inserted, expected_field, expected_value
):
    task_id = f"synthetic-{kind}"
    db = tmp_path / "android.db"
    with sqlite3.connect(db) as con:
        con.execute(ddl)
        table = {"sms": "sms_messages", "contacts": "contacts", "apps": "installed_packages", "wifi": "wifi_networks"}[kind]
        con.execute(f'INSERT INTO "{table}" VALUES({",".join("?" for _ in inserted)})', inserted)
    task = {"id": task_id, "output_files_db": str(db), "android_source": "dir"}
    detail = artifact_detail(task, kind, 1)
    result = freeze_selected_result(task, kind, 1, expected_row_hash=detail["record_hash"],
                                    expected_source_revision=detail["source_revision"])
    key = f"android_artifact:v1:{task_id}:{result['result_set_id']}:{kind}:1"
    cpp = AsyncMock()
    cpp.get_task = AsyncMock(return_value=task)
    resolved = asyncio.run(EvidenceResolver(cpp).resolve_evidence(task_id, key))
    snapshot = InvestigationRepository(tmp_path / "investigation.db", task_id).capture_if_absent(resolved)
    assert snapshot.payload.record_fields[expected_field] == expected_value
    assert snapshot.payload.normalized_fields[expected_field] == expected_value
    assert snapshot.payload.result_set_id == result["result_set_id"]
    assert snapshot.payload.provenance["original_primary_key"] is None
    if kind == "wifi":
        assert snapshot.payload.record_fields["pre_shared_key"] == "[redacted]"
        assert snapshot.payload.redacted_fields == ("pre_shared_key",)
    with pytest.raises(EvidenceNotFoundError):
        asyncio.run(EvidenceResolver(cpp).resolve_evidence("other-task", key))


def test_same_record_id_across_tasks_never_resolves_to_other_task(tmp_path):
    tasks = {}
    keys = {}
    for task_id, text in (("task-A", "A 的短信"), ("task-B", "B 的短信")):
        root = tmp_path / task_id
        root.mkdir()
        db = root / "android.db"
        with sqlite3.connect(db) as con:
            con.execute("CREATE TABLE sms_messages(id INTEGER PRIMARY KEY,address TEXT,body TEXT,date INTEGER,type INTEGER)")
            con.execute("INSERT INTO sms_messages VALUES(1,'10086',?,1700000000000,1)", (text,))
        task = {"id": task_id, "output_files_db": str(db), "android_source": "dir"}
        detail = artifact_detail(task, "sms", 1)
        result = freeze_selected_result(task, "sms", 1, expected_row_hash=detail["record_hash"],
                                        expected_source_revision=detail["source_revision"])
        tasks[task_id] = task
        keys[task_id] = f"android_artifact:v1:{task_id}:{result['result_set_id']}:sms:1"
    assert keys["task-A"] != keys["task-B"]

    class Cpp:
        async def get_task(self, task_id):
            return tasks.get(task_id)

    resolver = EvidenceResolver(Cpp())
    assert asyncio.run(resolver.resolve_evidence("task-A", keys["task-A"])).artifact_record_id == 1
    assert asyncio.run(resolver.resolve_evidence("task-B", keys["task-B"])).artifact_record_id == 1
    with pytest.raises(EvidenceNotFoundError):
        asyncio.run(resolver.resolve_evidence("task-B", keys["task-A"]))


def test_operator_v8_copy_preparation_never_mutates_source(tmp_path):
    root = tmp_path / "task-workspace"
    root.mkdir()
    source = root / "investigation.db"
    repo = InvestigationRepository.__new__(InvestigationRepository)
    repo.db_path, repo.task_id, repo.existing_only = source, "synthetic-migration", False
    repo._initialize_v7_atomically()
    with sqlite3.connect(source) as con:
        con.execute("INSERT INTO evidence_snapshots(task_id,evidence_key,evidence_type,normalized_path,snapshot_json,captured_at) VALUES(?,?,?,?,?,?)",
                    ("synthetic-migration", "file:/old", "file", "/old",
                     '{"evidence_type":"file","normalized_path":"/old"}', 1))
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    from httpserver.services.evidence.exceptions import EvidenceStoreError
    with pytest.raises(EvidenceStoreError, match="MIGRATION_REQUIRED"):
        InvestigationRepository(source, "synthetic-migration")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    task_record = tmp_path / "synthetic-task.json"
    task_record.write_text(json.dumps({"id": "synthetic-migration",
                                       "output_files_db": str(root / "files.db")}), encoding="utf-8")
    output = tmp_path / "prepared.db"
    cli = Path(__file__).resolve().parents[4] / "scripts" / "prepare_investigation_v8.py"
    result = subprocess.run([sys.executable, str(cli), "--task-record", str(task_record),
                             "--output-copy", str(output)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["cutover_performed"] is False
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert sqlite3.connect(source).execute("PRAGMA user_version").fetchone()[0] == 7
    assert sqlite3.connect(output).execute("PRAGMA user_version").fetchone()[0] == SUPPORTED_SCHEMA_VERSION
    assert InvestigationRepository(output, "synthetic-migration").get_snapshot("file:/old") is not None
    again = subprocess.run([sys.executable, str(cli), "--task-record", str(task_record),
                            "--output-copy", str(output)], capture_output=True, text=True, timeout=30)
    assert again.returncode != 0
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("decision", [AnalysisReviewDecision.rejected, AnalysisReviewDecision.invalid])
def test_rejected_or_invalid_android_analysis_cannot_be_report_binding(tmp_path, decision):
    db = tmp_path / "android.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE sms_messages(id INTEGER PRIMARY KEY,address TEXT,body TEXT,date INTEGER,type INTEGER)")
        con.execute("INSERT INTO sms_messages VALUES(1,'10086','合成',1,1)")
    task = {"id": "synthetic-review", "output_files_db": str(db), "android_source": "dir"}
    detail = artifact_detail(task, "sms", 1)
    result = freeze_selected_result(task, "sms", 1, expected_row_hash=detail["record_hash"],
                                    expected_source_revision=detail["source_revision"])
    key = f"android_artifact:v1:{task['id']}:{result['result_set_id']}:sms:1"

    class Cpp:
        async def get_task(self, _task_id):
            return task

    resolved = asyncio.run(EvidenceResolver(Cpp()).resolve_evidence(task["id"], key))
    repo = InvestigationRepository(tmp_path / "investigation.db", task["id"])
    snapshot = repo.capture_if_absent(resolved)
    analysis = repo.create_analysis(snapshot, prompt_version="investigation-evidence-analysis:v4")
    repo.transition(analysis.analysis_id, SecondaryAnalysisStatus.running)
    repo.complete_analysis_for_review(analysis.analysis_id, description="合成", summary="合成",
                                     model="test-only-mock", candidates=[])
    repo.review_analysis(analysis.analysis_id, decision=decision, reviewer="synthetic-reviewer")
    with pytest.raises(AnalysisBindingConflictError):
        repo.add_report_evidence(key, report_status="main", analysis_id=analysis.analysis_id,
                                 added_by="synthetic-reviewer")
