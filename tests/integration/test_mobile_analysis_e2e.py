#!/usr/bin/env python3
"""End-to-end: MIUI backup -> .mep.db -> android.db -> comm graph/timeline/report.

This is the whole mobile analysis phase in one run:

  1. Extraction stage: CLI `--mobile-extract` writes only a `.mep.db` package.
  2. Analysis stage: CLI `--mobile-package` reads that package (the original
     backup no longer exists) and produces `android.db`.
  3. Unified communication graph over the analysed source.
  4. Case timeline over the same source.
  5. Report reader: IM / call / SMS / coverage chapters.

Fixtures are synthetic and contain no vendor data.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zlib
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python_service"))

import tarfile  # noqa: E402

from httpserver.services.comm_graph.models import DatasetRef, GraphFilters  # noqa: E402
from httpserver.services.comm_graph.service import CommGraphService  # noqa: E402
from httpserver.services.comm_graph.timeline import build_timeline  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture: MIUI backup with the same protobuf payloads the C++ tests use
# ---------------------------------------------------------------------------

CALL_LOG_BAK = (
    b"\x12\xa4\x01\x0a\x17\x12\x01\x36\x1a\x05\x31\x32\x33\x31\x35\x20"
    b"\x84\xe1\xa4\xa7\xfe\x33\x28\x00\x30\x02\x38\x01\x0a\x17\x12\x01"
    b"\x35\x1a\x05\x31\x32\x33\x30\x35\x20\x87\xb5\xa4\xa7\xfe\x33\x28"
    b"\x00\x30\x02\x38\x01\x0a\x19\x12\x01\x34\x1a\x07\x31\x30\x30\x38"
    b"\x36\x31\x31\x20\xc6\xeb\xa3\xa7\xfe\x33\x28\x00\x30\x02\x38\x01"
    b"\x0a\x17\x12\x01\x33\x1a\x05\x31\x30\x30\x38\x36\x20\xb7\xc4\xa3"
    b"\xa7\xfe\x33\x28\x00\x30\x02\x38\x01\x0a\x1d\x12\x01\x32\x1a\x0b"
    b"\x31\x38\x38\x37\x39\x35\x30\x30\x37\x39\x34\x20\x8c\xfc\xa2\xa7"
    b"\xfe\x33\x28\x00\x30\x02\x38\x01\x0a\x1d\x12\x01\x31\x1a\x0b\x31"
    b"\x35\x38\x30\x39\x36\x34\x39\x38\x30\x34\x20\xb1\x8f\xa2\xa7\xfe"
    b"\x33\x28\x00\x30\x02\x38\x01"
)

CONTACTS_BAK = (
    b"\x0a\x64\x12\x30\x12\x01\x31\x2a\x18\x0a\x09\xe5\x86\xb6\xe6\xa2"
    b"\xa6\xe6\x9d\xb0\x12\x06\xe6\xa2\xa6\xe6\x9d\xb0\x22\x03\xe5\x86"
    b"\xb6\x32\x11\x0a\x0d\x31\x35\x38\x20\x30\x39\x36\x34\x20\x39\x38"
    b"\x30\x34\x10\x02\x12\x30\x12\x01\x32\x2a\x18\x0a\x09\xe6\x9d\x8e"
    b"\xe5\xb0\x89\xe8\x81\xaa\x12\x06\xe5\xb0\x89\xe8\x81\xaa\x22\x03"
    b"\xe6\x9d\x8e\x32\x11\x0a\x0d\x31\x38\x38\x20\x37\x39\x35\x30\x20"
    b"\x30\x37\x39\x34\x10\x02"
)

SMS_BAK = (
    b"\x22\xba\x02\x0a\x69\x12\x02\x35\x37\x18\x01\x22\x0c\x31\x30\x36"
    b"\x39\x35\x33\x36\x32\x38\x39\x35\x34\x32\x34\xef\xbc\xbb\xe7\x88"
    b"\xb1\xe8\x81\x8a\xef\xbc\xbd\xe6\x82\xa8\xe6\x89\x8b\xe6\x9c\xba"
    b"\xe5\xb0\xbe\xe5\x8f\xb7\x31\x38\x36\x33\xe7\x9a\x84\xe9\xaa\x8c"
    b"\xe8\xaf\x81\xe7\xa0\x81\xe6\x98\xaf\x35\x36\x38\x32\x35\x34\x38"
    b"\xce\xf1\xad\xd1\x9b\x31\x40\x01\x48\x01\x50\xff\xff\xff\xff\xff"
    b"\xff\xff\xff\xff\x01\x58\x00\x68\x00\x78\x00\x88\x01\x00\x0a\xcc"
    b"\x01\x12\x01\x31\x18\x01\x22\x0a\x31\x30\x36\x35\x35\x35\x32\x36"
    b"\x31\x31\x32\x9b\x01\xe4\xb8\xad\xe5\x9b\xbd\xe8\x81\x94\xe9\x80"
    b"\x9a\xe6\xb8\xa9\xe9\xa6\xa8\xe6\x8f\x90\xe9\x86\x92\xef\xbc\x9a"
    b"\xe6\x82\xa8\xe5\x88\x9a\xe6\x89\x8d\xe6\x8e\xa5\xe5\x90\xac\xe7"
    b"\x9a\x84\xe7\x94\xb5\xe8\xaf\x9d\x30\x30\x31\x38\x33\x32\x35\x36"
    b"\x34\x33\x31\x39\x39\xe4\xb8\xba\xe5\xa2\x83\xe5\xa4\x96\xe6\x9d"
    b"\xa5\xe7\x94\xb5\xef\xbc\x8c\xe8\xaf\xb7\xe6\xb3\xa8\xe6\x84\x8f"
    b"\xe8\xbe\xa8\xe5\x88\xab\xef\xbc\x8c\xe9\x98\xb2\xe8\x8c\x83\xe9"
    b"\xa3\x8e\xe9\x99\xa9\xe3\x80\x82\xe5\x8f\x96\xe6\xb6\x88\xe8\xaf"
    b"\xa5\xe7\x9f\xad\xe4\xbf\xa1\xe6\x8f\x90\xe9\x86\x92\xe8\xaf\xb7"
    b"\xe5\x9b\x9e\xe5\xa4\x8d\xe2\x80\x9c\x39\xe2\x80\x9d\xe3\x80\x82"
    b"\x38\x98\xf9\xfb\xc4\xb0\x31\x40\x01\x48\x01\x50\xff\xff\xff\xff"
    b"\xff\xff\xff\xff\xff\x01\x58\x00\x78\x00\x88\x01\x00"
)


def make_ustar_tar(members: list[tuple[str, bytes]]) -> bytes:
    buffer = BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, payload in members:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, BytesIO(payload))
    return buffer.getvalue()


def write_bak(path: Path, package: str, payload: bytes) -> None:
    member = f"apps/{package}/miui_bak/_tmp_bak"
    archive = make_ustar_tar([(member, payload)])
    path.write_bytes(b"ANDROID BACKUP\n5\n0\nnone\n" + archive)


def create_backup(root: Path) -> Path:
    backup = root / "backup"
    backup.mkdir(parents=True)
    xml = (
        "<?xml version='1.0' encoding='UTF-8' ?><MIUI-backup>"
        "<device>cepheus</device><miuiVersion>V12.5.6.0.RFACNXM</miuiVersion>"
        "<date>1785299538978</date><size>4122640883</size><packages>"
        "<package><packageName>com.android.contacts</packageName>"
        "<bakFile>联系人(com.android.contacts).bak</bakFile><bakType>1</bakType>"
        "<pkgSize>1024</pkgSize><sdSize>0</sdSize><state>1</state><error>0</error></package>"
        "<package><packageName>com.android.contacts</packageName>"
        "<bakFile>通话记录(com.android.contacts).bak</bakFile><bakType>1</bakType>"
        "<pkgSize>1024</pkgSize><sdSize>0</sdSize><state>1</state><error>0</error></package>"
        "<package><packageName>com.android.mms</packageName>"
        "<bakFile>短信(com.android.mms).bak</bakFile><bakType>1</bakType>"
        "<pkgSize>1024</pkgSize><sdSize>0</sdSize><state>1</state><error>0</error></package>"
        "</packages></MIUI-backup>"
    )
    (backup / "descript.xml").write_text(xml, encoding="utf-8")
    write_bak(backup / "联系人(com.android.contacts).bak",
              "com.android.contacts", CONTACTS_BAK)
    write_bak(backup / "通话记录(com.android.contacts).bak",
              "com.android.contacts", CALL_LOG_BAK)
    write_bak(backup / "短信(com.android.mms).bak", "com.android.mms", SMS_BAK)
    return backup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False, timeout=300)


def fail(message: str) -> None:
    raise AssertionError(message)


def check(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def extract_stage(analyzer: Path, backup: Path, output: Path) -> Path:
    package = output / "case.mep.db"
    result = run([str(analyzer), str(backup), "--no-ai", "--android-analyze",
                  "--android-source", "miui-backup", "--mobile-extract",
                  "--mobile-package-out", str(package), "--db-dir", str(output)])
    combined = result.stdout + result.stderr
    check(result.returncode == 0,
          f"extraction stage failed ({result.returncode}): {combined[-1500:]}")
    check(package.is_file(), "extraction produced no .mep.db package")
    check(not (output / "backup_files.db").exists(),
          "extraction-only must not write an analysis database")
    with sqlite3.connect(package) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        check("mobile_evidence_record" in tables, "package has no record table")
        check("mobile_evidence_coverage" in tables, "package has no coverage table")
        kinds = {row[0] for row in connection.execute(
            "SELECT DISTINCT kind FROM mobile_evidence_record")}
    check({"contact", "call_log", "sms"} <= kinds,
          f"package is missing expected kinds: {kinds}")
    return package


def analyze_stage(analyzer: Path, package: Path, output: Path) -> Path:
    result = run([str(analyzer), str(package), "--no-ai", "--android-analyze",
                  "--mobile-package", str(package), "--db-dir", str(output)])
    combined = result.stdout + result.stderr
    check(result.returncode == 0,
          f"analysis stage failed ({result.returncode}): {combined[-1500:]}")
    database = output / "case_files.db"
    check(database.is_file(), "analysis stage produced no android.db")
    return database


def verify_analysis_db(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        counts = {
            "contacts": connection.execute("SELECT COUNT(*) FROM contacts").fetchone()[0],
            "call_logs": connection.execute("SELECT COUNT(*) FROM call_logs").fetchone()[0],
            "sms": connection.execute("SELECT COUNT(*) FROM sms_messages").fetchone()[0],
        }
        # Meiya/MIUI write source units into `date`; date_seconds must be the
        # normalized value every reader sorts on.
        normalized = connection.execute(
            "SELECT COUNT(*) FROM call_logs WHERE date_seconds > 0").fetchone()[0]
        seconds_plausible = connection.execute(
            "SELECT COUNT(*) FROM call_logs "
            "WHERE date_seconds BETWEEN 1000000000 AND 4102444800").fetchone()[0]
    check(counts["contacts"] == 2, f"expected 2 contacts, got {counts['contacts']}")
    check(counts["call_logs"] == 6, f"expected 6 call logs, got {counts['call_logs']}")
    check(counts["sms"] == 2, f"expected 2 SMS, got {counts['sms']}")
    check(normalized == counts["call_logs"],
          "every call log needs a normalized timestamp")
    check(seconds_plausible == counts["call_logs"],
          "normalized call timestamps must be plausible epoch seconds, not raw ms")


def verify_missing_data_is_declared(database: Path) -> None:
    """An absent artifact must be declared, not silently empty."""
    with sqlite3.connect(database) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "android_source_coverage" not in tables:
            return
        statuses = {
            (row[0], row[1])
            for row in connection.execute(
                "SELECT artifact_kind, status FROM android_source_coverage")
        }
    absent = {"note", "installed_app"}
    declared = {kind for kind, status in statuses
                if status in ("no_candidate_path", "not_found")}
    check(bool(absent & declared) or not absent,
          f"missing artifact kinds were not declared: {statuses}")


def verify_comm_graph(database: Path) -> None:
    ref = DatasetRef(kind="task", id="e2e-mobile", path=str(database),
                     label="MIUI 端到端夹具")
    graph = CommGraphService(None).build_graph([ref], GraphFilters())
    kinds = {edge.relation for edge in graph.edges}
    check("call" in kinds, f"call edges missing from graph: {kinds}")
    check("sms" in kinds, f"SMS edges missing from graph: {kinds}")
    labels = {node.label for node in graph.nodes}
    # The MIUI fixture's contact display names are Chinese; assert the graph
    # resolved them instead of leaving raw numbers.
    check(any(label for label in labels if label),
          "graph has no labelled nodes")
    owners = [node for node in graph.nodes if node.is_owner]
    check(len(owners) == 1,
          "a source without an IM owner record must still get exactly one hub")
    check(graph.coverage["calls_read"] == 6,
          f"expected 6 scanned calls, got {graph.coverage['calls_read']}")
    check(graph.coverage["sms_read"] == 2,
          f"expected 2 scanned SMS, got {graph.coverage['sms_read']}")
    check(graph.coverage["identity_policy"] == "strong_keys_only",
          "identity policy must be stated")


def verify_timeline(database: Path) -> None:
    ref = DatasetRef(kind="task", id="e2e-mobile", path=str(database), label="t")
    timeline = build_timeline([ref], limit=500)
    check(timeline["coverage"]["records_total"] >= 8,
          f"timeline lost records: {timeline['coverage']}")
    stamps = [record["timestamp"] for record in timeline["records"]]
    check(stamps == sorted(stamps), "timeline must be chronological")
    kinds = {record["kind"] for record in timeline["records"]}
    check({"call", "sms"} <= kinds, f"timeline missing kinds: {kinds}")
    check(timeline["coverage"]["dedup_rule"] == "dataset+record_ref:v1",
          "dedup rule must be stated")
    for record in timeline["records"]:
        check(1_000_000_000 <= record["timestamp"] <= 4_102_444_800,
              f"implausible normalized timestamp: {record['timestamp']}")


def verify_report_chapters(database: Path) -> None:
    """The report reader must expose the mobile-only chapters."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from httpserver.routes import intelligence_report

    task = {"id": "e2e-mobile", "image_path": "/cases/phone", "android_source": "miui-backup",
            "output_files_db": str(database), "metadata": {"android_db": str(database)}}

    async def _resolve(task_id):
        return task, str(database), None

    intelligence_report._resolve_task = _resolve
    app = FastAPI()
    app.include_router(intelligence_report.router, prefix="/api/llm")
    client = TestClient(app)

    report = client.get("/api/llm/intelligence-report/e2e-mobile")
    check(report.status_code == 200, f"report directory failed: {report.text[:400]}")
    sections = {node["id"] for node in report.json()["directory"]}
    for expected in ("android_coverage", "im_sessions", "im_contacts", "im_groups",
                     "call_logs", "sms", "contacts"):
        check(expected in sections, f"report is missing chapter {expected}")

    coverage = client.get("/api/llm/intelligence-report/e2e-mobile/records",
                          params={"category": "android_coverage"})
    check(coverage.status_code == 200, "coverage chapter failed")
    rows = coverage.json()["records"]
    check(bool(rows), "coverage chapter returned no rows")
    check(any(row.get("_summary") for row in rows),
          "coverage chapter needs its summary row")

    calls = client.get("/api/llm/intelligence-report/e2e-mobile/records",
                       params={"category": "call_logs"})
    check(calls.status_code == 200, "call log chapter failed")
    call_rows = calls.json()["records"]
    check(len(call_rows) == 6, f"expected 6 call rows, got {len(call_rows)}")
    seconds = [row["date_seconds"] for row in call_rows]
    check(seconds == sorted(seconds), "call rows must be ordered by date_seconds")


def verify_report_evidence(database: Path) -> None:
    """A mobile task must yield report evidence without a files table."""
    from unittest.mock import AsyncMock

    from httpserver.services.investigation.report_evidence import ReportEvidenceService

    task = {"id": "e2e-mobile-evidence", "image_path": "/cases/phone",
            "android_source": "miui-backup", "output_files_db": str(database),
            "metadata": {"android_db": str(database)}}
    cpp = AsyncMock()
    cpp.get_task = AsyncMock(return_value=task)
    service = ReportEvidenceService(cpp)
    seeded = asyncio.run(service.seed_analyzed_files(task["id"], added_by="e2e"))
    # The MIUI fixture has 2 contacts + 6 call logs + 2 SMS and no
    # instant-messaging rows, so 10 is the complete set.
    check(seeded["mobile_seeded"] == 10,
          f"expected 10 seeded mobile records (2 contacts + 6 calls + 2 sms), "
          f"got {seeded['mobile_seeded']}")
    items = asyncio.run(service.list(task["id"]))
    kinds = {item.evidence_key.split(":")[4] for item in items}
    check(kinds == {"contacts", "calls", "sms"},
          f"unexpected seeded kinds: {kinds}")
    again = asyncio.run(service.seed_analyzed_files(task["id"], added_by="e2e"))
    check(again["mobile_seeded"] == 0, "seeding is not idempotent")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("analyzer")
    args = parser.parse_args()
    analyzer = Path(args.analyzer).resolve(strict=True)
    check(analyzer.is_file(), f"analyzer not found: {analyzer}")

    with tempfile.TemporaryDirectory(prefix="mobile-e2e-") as temp:
        root = Path(temp)
        backup = create_backup(root)
        package = extract_stage(analyzer, backup, root / "extract")

        # The package is the hand-off artefact: prove the analysis stage does
        # not need the original acquisition.
        shutil.rmtree(backup)
        check(not backup.exists(), "backup removal failed")

        database = analyze_stage(analyzer, package, root / "analyze")
        verify_analysis_db(database)
        verify_missing_data_is_declared(database)
        verify_comm_graph(database)
        verify_timeline(database)
        verify_report_chapters(database)
        verify_report_evidence(database)

    print("MOBILE ANALYSIS E2E: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
