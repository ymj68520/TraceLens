"""Harmony records use the existing frozen Android evidence/report contract."""
import asyncio
import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

from httpserver.services.android_artifact_reader import artifact_detail, list_artifacts
from httpserver.services.android_result_sets import freeze_selected_result
from httpserver.services.evidence.resolver import EvidenceResolver
from httpserver.services.investigation.acquisition import _acquire_android_artifact
from httpserver.services.evidence_preflight import _probe


def test_decrypted_backup_detection_is_structural(tmp_path):
    (tmp_path / "files").mkdir()
    header = tmp_path / ".info.json"
    header.write_text(json.dumps({"BackupFileHeaderInfo": {"deviceModel": "fixture"}, "BackupFileModuleInfo": []}))
    assert _probe(tmp_path)["adapter"] == "harmony-backup"
    header.write_text('{"deviceModel":"Huawei"}')
    assert _probe(tmp_path)["kind"] == "unknown_directory"


def test_mobile_record_freezes_and_retains_source_key_in_investigation(tmp_path):
    db = tmp_path / "android.db"
    source = "/harmony/com.huawei.hmos.calendardata/0/data/storage/el2/database/entry/rdb/calendardata.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE mobile_artifacts(id INTEGER PRIMARY KEY,kind TEXT,package_name TEXT,app_index INTEGER,"
                    "source_path TEXT,source_table TEXT,source_key TEXT,record_json TEXT,timestamp_raw TEXT,time_unit TEXT,"
                    "timestamp_seconds INTEGER,source_db_sha256 TEXT,source_wal_sha256 TEXT,parser_version TEXT)")
        con.execute("INSERT INTO mobile_artifacts VALUES(1,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            "calendar", "com.huawei.hmos.calendardata", 0, source, "Events", '{"_id":7}',
            '{"title":"test event","dtstart":1700000000000}', "1700000000000", "epoch_ms",
            1700000000, "a" * 64, "b" * 64, "harmony-decrypted-v1"))
        con.execute("CREATE TABLE android_source_coverage(artifact_kind TEXT,source_path TEXT,status TEXT,detail TEXT)")
        con.execute("INSERT INTO android_source_coverage VALUES('calendar',?,'parsed','rows=1')", (source,))
        con.execute("CREATE TABLE android_source_provenance(normalized_android_path TEXT,source_member_path TEXT,"
                    "source_container TEXT,source_container_sha256 TEXT)")
        con.execute("INSERT INTO android_source_provenance VALUES(?,?,?,?)", (source,
            "/data/storage/el2/database/entry/rdb/calendardata.db", "part.0.tarx", "c" * 64))
    task = {"id": "harmony-fixture", "output_files_db": str(db), "android_source": "harmony-backup",
            "metadata": {"android_db": str(db)}}
    assert list_artifacts(task, "mobile", query="test event")["total"] == 1
    detail = artifact_detail(task, "mobile", 1)
    assert detail["source"]["original_primary_key"] == {"_id": 7}
    assert detail["source"]["wal_frame"] is None
    frozen = freeze_selected_result(task, "mobile", 1, expected_row_hash=detail["record_hash"],
                                    expected_source_revision=detail["source_revision"])
    key = f"android_artifact:v1:{task['id']}:{frozen['result_set_id']}:mobile:1"
    cpp = AsyncMock()
    cpp.get_task = AsyncMock(return_value=task)
    resolved = asyncio.run(EvidenceResolver(cpp).resolve_evidence(task["id"], key))
    snapshot = _acquire_android_artifact(resolved)
    assert snapshot.artifact_kind == "mobile"
    assert snapshot.provenance["original_table"] == "Events"
    assert snapshot.provenance["original_primary_key"] == {"_id": 7}
    assert snapshot.provenance["wal_frame"] is None
    assert snapshot.timestamp_unit == "epoch_ms"
    assert snapshot.parser_version == "harmony-decrypted-v1"
    assert snapshot.normalized_fields["platform"] == "HarmonyOS"
    # The ordinary pipeline report seeder also adopts analyzed mobile rows.
    # The test substitutes an existing analysis result, never a real model call.
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE files(path TEXT,llm_analyzed_at INTEGER)")
        con.execute("ALTER TABLE mobile_artifacts ADD COLUMN llm_analyzed_at INTEGER")
        con.execute("ALTER TABLE mobile_artifacts ADD COLUMN llm_description TEXT")
        con.execute("UPDATE mobile_artifacts SET llm_analyzed_at=1,llm_description='Synthetic calendar analysis'")
    from httpserver.services.investigation.report_evidence import ReportEvidenceService
    service = ReportEvidenceService(cpp)
    seeded = asyncio.run(service.seed_analyzed_files(task["id"], added_by="pipeline"))
    assert seeded["mobile_seeded"] == 1
    items = asyncio.run(service.list(task["id"]))
    assert len(items) == 1 and ":mobile:1" in items[0].evidence_key
    repeated = asyncio.run(service.seed_analyzed_files(task["id"], added_by="pipeline"))
    assert repeated["mobile_seeded"] == 0
    from httpserver.services.investigation.paths import investigation_db_path_for_task
    with sqlite3.connect(investigation_db_path_for_task(task)) as con:
        con.execute("UPDATE report_evidence SET report_status='excluded'")
    assert asyncio.run(service.seed_analyzed_files(task["id"], added_by="pipeline"))["mobile_seeded"] == 0
    assert asyncio.run(service.list(task["id"]))[0].report_status == "excluded"
    from httpserver.services.android_field_package import build_package, verify_package
    package = tmp_path / "delivery"
    manifest = build_package(output=package, task=task)
    assert manifest["counts"]["mobile_artifacts"] == 1
    assert verify_package(package)["valid"] is True
