#!/usr/bin/env python3
"""Real-sample acceptance test for the generic ThunderForensic adapter.

Runs the analyzer against the three ThunderForensic project folders used
during development (20261025OPPO / 20261025OnePlus / 20261025VIVO). The
samples are external evidence, so the test skips cleanly when the root is not
present. Pass --samples-root or set TRACELENS_THUNDERFORENSIC_SAMPLES.

Assertions cover the vendor-specific shapes that motivated the generic module:
vivo's first-member non-octal gid, manifest at the end, 486 duplicate members,
chunk-framed wifi.xml and encrypted note archives; OnePlus per-package .tar
trees; OPPO PhoneData-only extraction; and the integrity policy for the 53 GiB
vivo container.
"""

import argparse
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

DEFAULT_SAMPLES = Path("/mnt/d/测试/测试镜像/手机")


def api(url, data=None):
    req = Request(url, data=json.dumps(data).encode() if data is not None else None,
                  headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=10) as response:
        return response.status, json.load(response)


def run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run([*command, "--no-ai"], capture_output=True, text=True,
                          check=False, timeout=timeout)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def open_counts(database: Path) -> tuple[sqlite3.Connection, dict, dict, dict]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    kinds = dict(connection.execute(
        "SELECT kind, COUNT(*) FROM mobile_artifacts GROUP BY kind"))
    tables = {}
    for table in ("installed_apps", "contacts", "call_logs", "sms_messages",
                  "wifi_networks", "device_identifiers", "android_source_coverage",
                  "android_source_provenance", "android_container_coverage"):
        tables[table] = connection.execute(
            f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    coverage = {row["source_path"]: (row["status"], row["detail"]) for row in
                connection.execute(
                    "SELECT source_path, status, detail FROM android_source_coverage")}
    return connection, kinds, tables, coverage


def verify_reader_contract(database: Path, vendor: str, context: str) -> None:
    """Every mobile_artifacts row must satisfy the artifact reader contract.

    android_artifact_reader.artifact_detail json.loads(source_key) as the row
    primary key and reads mobile_backup_manifest.platform for the label; a
    bare string key or a missing platform breaks report evidence seeding.
    The real reader is used when its package dependencies are importable;
    otherwise the same two invariants are checked directly so the test still
    runs on a bare python3.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python_service"))
    try:
        from httpserver.services import android_artifact_reader as reader
        from httpserver.services.android_result_sets import (
            freeze_selected_result as freeze)
    except ImportError:
        reader = freeze = None

    task = {"id": "real-sample", "metadata": {"android_db": str(database)},
            "output_files_db": str(database)}
    with sqlite3.connect(database) as con:
        rows = con.execute(
            "SELECT id, kind, source_key FROM mobile_artifacts ORDER BY id").fetchall()
        manifest = con.execute(
            "SELECT platform FROM mobile_backup_manifest LIMIT 1").fetchone()
    assert_true(rows, f"{context}: no mobile artifacts to read")
    assert_true(manifest is not None and manifest[0] == "Android",
                f"{context}: manifest platform {manifest}")
    seen = set()
    for row_id, kind, source_key in rows:
        key = json.loads(source_key)
        assert_true(isinstance(key, dict),
                    f"{context}: {kind} key is not an object: {source_key!r}")
        if reader is None or kind in seen:
            seen.add(kind)
            continue
        seen.add(kind)
        detail = reader.artifact_detail(task, "mobile", row_id)
        assert_true(detail["source"]["platform"] == "Android",
                    f"{context}: {kind} platform {detail['source']['platform']}")
        assert_true(detail["source"]["original_primary_key"] == key,
                    f"{context}: {kind} key {detail['source']['original_primary_key']!r}")
        frozen = freeze(task, "mobile", row_id,
                        expected_row_hash=detail["record_hash"],
                        expected_source_revision=detail["source_revision"])
        assert_true(frozen["source_revision"] == detail["source_revision"],
                    f"{context}: {kind} freeze revision drift")
    mode = "reader+freeze" if reader is not None else "direct JSON contract"
    print(f"{vendor}: {mode} OK for {len(seen)} artifact kinds")


def verify_oppo(analyzer: Path, project: Path, output: Path) -> None:
    result = run([str(analyzer), str(project), "--android-analyze",
                  "--android-source", "oppo-backup", "--db-dir", str(output)],
                 timeout=600)
    combined = result.stdout + result.stderr
    assert_true(result.returncode == 0, f"OPPO analysis failed: {combined}")
    database = output / "20261025OPPO_files.db"
    connection, kinds, tables, coverage = open_counts(database)
    try:
        manifest = connection.execute(
            "SELECT platform, device, backup_version, module_count, adapter_version "
            "FROM mobile_backup_manifest").fetchone()
        assert_true(tuple(manifest) == ("Android", "OPPO PBEM00", "4.9.3.32581", 19,
                                        "thunderforensic-v2"),
                    f"OPPO manifest: {tuple(manifest)}")
        # Container (tar) layer.
        assert_true(kinds.get("application", 0) >= 345, f"OPPO kinds: {kinds}")
        assert_true(kinds.get("app_traffic") == 348, f"OPPO kinds: {kinds}")
        assert_true(kinds.get("app_usage_session") == 58, f"OPPO kinds: {kinds}")
        assert_true(kinds.get("media") == 22, f"OPPO kinds: {kinds}")
        assert_true(kinds.get("device_log") == 15, f"OPPO kinds: {kinds}")
        # Case-database layer fills what PhoneData does not carry.
        assert_true(kinds.get("file_inventory") == 64, f"OPPO kinds: {kinds}")
        assert_true(kinds.get("case_loginfo") == 89, f"OPPO kinds: {kinds}")
        assert_true(tables["installed_apps"] >= 345, f"OPPO tables: {tables}")
        assert_true(tables["wifi_networks"] == 2, f"OPPO tables: {tables}")
        aggregate = coverage["<data>"]
        assert_true("databases=7" in aggregate[1], f"OPPO case aggregate: {aggregate}")
        assert_true("skipped_duplicate_rows=" in aggregate[1],
                    f"OPPO case aggregate: {aggregate}")
        assert_true(coverage["evidence_1_file"][0] == "parsed",
                    f"OPPO case file inventory: {coverage['evidence_1_file']}")
        assert_true(coverage["evidence_1_wifi"][0] == "empty",
                    f"OPPO case wifi should dedupe: {coverage['evidence_1_wifi']}")
        assert_true(tables["android_source_provenance"] >= 27,
                    f"OPPO provenance: {tables}")
        assert_true("SecurityException" in coverage["PhoneData/siminfo.json"][1],
                    f"OPPO extractor error missing: {coverage}")
        container = connection.execute(
            "SELECT reason FROM android_container_coverage").fetchone()["reason"]
        assert_true("container_sha256_status=sha256" in container,
                    f"OPPO container: {container}")
        assert_true("duplicate_members=0" in container, f"OPPO container: {container}")
        print(f"OPPO   artifacts={sum(kinds.values())} installed={tables['installed_apps']} "
              f"wifi={tables['wifi_networks']} case_dbs=7")
    finally:
        connection.close()
    verify_reader_contract(database, "OPPO", "OPPO real sample")


def verify_oneplus(analyzer: Path, project: Path, output: Path) -> None:
    result = run([str(analyzer), str(project), "--android-analyze",
                  "--android-source", "thunder-backup", "--db-dir", str(output)],
                 timeout=900)
    combined = result.stdout + result.stderr
    assert_true(result.returncode == 0, f"OnePlus analysis failed: {combined}")
    database = output / "20261025OnePlus_files.db"
    connection, kinds, tables, coverage = open_counts(database)
    try:
        manifest = connection.execute(
            "SELECT platform, device, adapter_version FROM mobile_backup_manifest"
        ).fetchone()
        assert_true(tuple(manifest) == ("Android", "OnePlus GM1910", "thunderforensic-v2"),
                    f"OnePlus manifest: {tuple(manifest)}")
        assert_true(kinds.get("application", 0) >= 340, f"OnePlus kinds: {kinds}")
        assert_true(kinds.get("app_data_container", 0) >= 4, f"OnePlus kinds: {kinds}")
        assert_true(kinds.get("app_database", 0) >= 20, f"OnePlus kinds: {kinds}")
        assert_true(kinds.get("device_log") == 15, f"OnePlus kinds: {kinds}")
        # Case-database layer: browsing/download history and file inventory are
        # only present there (PhoneData has no webhistory member).
        assert_true(kinds.get("web_history") == 86, f"OnePlus kinds: {kinds}")
        assert_true(kinds.get("search_history") == 25, f"OnePlus kinds: {kinds}")
        assert_true(kinds.get("download") == 6, f"OnePlus kinds: {kinds}")
        assert_true(kinds.get("file_inventory") == 5067, f"OnePlus kinds: {kinds}")
        assert_true("databases=10" in coverage["<data>"][1],
                    f"OnePlus case aggregate: {coverage['<data>']}")
        assert_true(tables["installed_apps"] >= 340, f"OnePlus tables: {tables}")
        assert_true(tables["wifi_networks"] == 3, f"OnePlus tables: {tables}")
        assert_true(coverage["<containers>"][0] == "indexed",
                    f"OnePlus app data: {coverage['<containers>']}")
        containers = {row["source_path"] for row in connection.execute(
            "SELECT source_path FROM mobile_artifacts WHERE kind='app_data_container'")}
        assert_true("com.android.chrome.tar" in containers,
                    f"OnePlus chrome container missing: {containers}")
        container = connection.execute(
            "SELECT reason FROM android_container_coverage").fetchone()["reason"]
        assert_true("container_sha256_status=sha256" in container,
                    f"OnePlus container: {container}")
        print(f"OnePlus artifacts={sum(kinds.values())} installed={tables['installed_apps']} "
              f"app_containers={kinds.get('app_data_container', 0)} "
              f"app_dbs={kinds.get('app_database', 0)}")
    finally:
        connection.close()
    verify_reader_contract(database, "OnePlus", "OnePlus real sample")


def verify_vivo(analyzer: Path, project: Path, output: Path) -> None:
    result = run([str(analyzer), str(project), "--android-analyze",
                  "--android-source", "thunder-backup", "--db-dir", str(output)],
                 timeout=2400)
    combined = result.stdout + result.stderr
    assert_true(result.returncode == 0, f"vivo analysis failed: {combined}")
    database = output / "20261025VIVO_files.db"
    connection, kinds, tables, coverage = open_counts(database)
    try:
        manifest = connection.execute(
            "SELECT platform, device, module_count, adapter_version "
            "FROM mobile_backup_manifest").fetchone()
        assert_true(tuple(manifest) == ("Android", "vivo V1824BA", 15, "thunderforensic-v2"),
                    f"vivo manifest: {tuple(manifest)}")
        assert_true(kinds.get("application", 0) >= 493, f"vivo kinds: {kinds}")
        assert_true(kinds.get("contact") == 7005, f"vivo kinds: {kinds}")
        assert_true(kinds.get("call_log") == 5050, f"vivo kinds: {kinds}")
        assert_true(kinds.get("media") == 5824, f"vivo kinds: {kinds}")
        # Case-database layer: SMS exists only here (no PhoneData/smss.json),
        # plus IM messages, mail, browsing history and the file inventory.
        assert_true(kinds.get("sms") == 2079, f"vivo kinds: {kinds}")
        assert_true(kinds.get("im_message") == 49160, f"vivo kinds: {kinds}")
        assert_true(kinds.get("im_contact") == 27557, f"vivo kinds: {kinds}")
        assert_true(kinds.get("mail") == 440, f"vivo kinds: {kinds}")
        assert_true(kinds.get("web_history") == 213, f"vivo kinds: {kinds}")
        assert_true("databases=48" in coverage["<data>"][1],
                    f"vivo case aggregate: {coverage['<data>']}")
        truncated = {path for path, (status, _) in coverage.items()
                     if status == "PARTIAL"}
        assert_true("evidence_1_cloudfile" in truncated,
                    f"vivo truncation not reported: {truncated}")
        assert_true(kinds.get("app_data_container") == 165, f"vivo kinds: {kinds}")
        assert_true(kinds.get("app_database") == 1762, f"vivo kinds: {kinds}")
        assert_true(kinds.get("note_archive") == 2, f"vivo kinds: {kinds}")
        assert_true(kinds.get("device_marker") == 1, f"vivo kinds: {kinds}")
        assert_true(kinds.get("encrypted_artifact") == 2, f"vivo kinds: {kinds}")
        assert_true(tables["installed_apps"] >= 493, f"vivo tables: {tables}")
        assert_true(tables["contacts"] == 7005, f"vivo tables: {tables}")
        assert_true(tables["call_logs"] == 5010, f"vivo tables: {tables}")
        assert_true(tables["sms_messages"] == 2079, f"vivo tables: {tables}")
        assert_true(tables["wifi_networks"] == 23, f"vivo tables: {tables}")
        assert_true(tables["android_source_provenance"] >= 20,
                    f"vivo provenance: {tables}")
        assert_true(coverage["wifi.xml"][0] == "parsed",
                    f"vivo wifi.xml: {coverage['wifi.xml']}")
        assert_true(coverage["note.zip"][0] == "LOCKED",
                    f"vivo note.zip: {coverage['note.zip']}")
        assert_true(coverage["encryptNote.zip"][0] == "LOCKED",
                    f"vivo encryptNote.zip: {coverage['encryptNote.zip']}")
        assert_true(coverage["<containers>"][0] == "indexed",
                    f"vivo app data: {coverage['<containers>']}")
        container = connection.execute(
            "SELECT reason FROM android_container_coverage").fetchone()["reason"]
        assert_true("container_sha256_status=not_computed_large_container" in container,
                    f"vivo container: {container}")
        assert_true("duplicate_members=486" in container, f"vivo container: {container}")
        networks = {row["ssid"] for row in connection.execute(
            "SELECT ssid FROM wifi_networks")}
        assert_true("131" in networks and "ASUS_5G" in networks,
                    f"vivo wifi ssids missing: {sorted(networks)[:10]}")
        print(f"vivo   artifacts={sum(kinds.values())} installed={tables['installed_apps']} "
              f"contacts={tables['contacts']} calls={tables['call_logs']} "
              f"wifi={tables['wifi_networks']} app_containers={kinds.get('app_data_container')} "
              f"app_dbs={kinds.get('app_database')}")
    finally:
        connection.close()
    verify_reader_contract(database, "vivo", "vivo real sample")


def verify_raw_tar(analyzer: Path, project: Path, output: Path) -> None:
    tars = sorted((project / "filesystem" / "1" / "tar").glob("*.tar"))
    assert_true(len(tars) == 1, f"expected one tar in {project}: {tars}")
    result = run([str(analyzer), str(tars[0]), "--android-analyze",
                  "--android-source", "thunder-backup", "--db-dir", str(output)],
                 timeout=600)
    combined = result.stdout + result.stderr
    assert_true(result.returncode == 0, f"raw tar analysis failed: {combined}")
    database = output / (tars[0].stem.replace("-", "-") + "_files.db")
    if not database.exists():
        candidates = list(output.glob("*_files.db"))
        assert_true(len(candidates) == 1, f"raw tar DB not found: {list(output.iterdir())}")
        database = candidates[0]
    connection, kinds, tables, _ = open_counts(database)
    try:
        assert_true(kinds.get("application") == 345, f"raw tar kinds: {kinds}")
        assert_true(tables["installed_apps"] == 345, f"raw tar tables: {tables}")
    finally:
        connection.close()
    print(f"OPPO   raw tar route artifacts={sum(kinds.values())}")


def verify_real_http_task(binary: Path, project: Path, root: Path,
                          expected: dict) -> None:
    """One real project folder through the actual HTTP task pipeline.

    A fresh isolated server is started on a random port with its own DATA_DIR;
    no shared/long-running service is touched.
    """

    class TailStub(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_json(self, value):
            payload = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            self.send_json({"job_id": "real-sample", "status": "completed"})

        def do_GET(self):
            self.send_json({"status": "COMPLETED", "progress": 100,
                            "current_phase": "completed"})

    stub = ThreadingHTTPServer(("127.0.0.1", 0), TailStub)
    threading.Thread(target=stub.serve_forever, daemon=True).start()
    try:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        env = dict(os.environ, DATA_DIR=str(root / "data"), LLM_ENABLED="false",
                   PYTHON_SERVICE_URL=f"http://127.0.0.1:{stub.server_port}",
                   GRAPHITI_INGEST_WAIT_TIMEOUT_MIN="1")
        root.mkdir(parents=True, exist_ok=True)
        log = (root / "server.log").open("w")
        server = subprocess.Popen([str(binary), "--http-server", str(port)],
                                  cwd=Path(__file__).resolve().parents[2],
                                  env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(300):
                try:
                    if api(base + "/api/health")[0] == 200:
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise AssertionError("isolated server did not start")
            status, created = api(base + "/api/tasks", {
                "image_path": str(project), "android_source": "dir",
                "scenarios": ["android"], "platform_analyze": True,
                "llm_analyze": False, "filter_profile": "general_forensics"})
            assert_true(status == 201, f"real HTTP task rejected: {created}")
            task_id = created["id"]
            for _ in range(2400):
                _, task = api(base + "/api/tasks/" + task_id)
                if task["status"].lower() in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(0.25)
            assert_true(task["status"].lower() == "completed", f"real HTTP task: {task}")
            assert_true(task["android_source"] == "thunder-backup",
                        f"real HTTP source: {task['android_source']}")
            assert_true(task["metadata"].get("device_brand") == expected["brand"],
                        f"real HTTP brand: {task['metadata']}")
            assert_true(task["metadata"].get("device_model") == expected["model"],
                        f"real HTTP model: {task['metadata']}")
            expected_device = f"{expected['brand']} {expected['model']}"
            with sqlite3.connect(task["metadata"]["android_db"]) as con:
                manifest = con.execute(
                    "SELECT device, adapter_version FROM mobile_backup_manifest"
                ).fetchone()
                assert_true(manifest == (expected_device, "thunderforensic-v2"),
                            f"real HTTP manifest: {manifest}")
                artifacts = con.execute(
                    "SELECT COUNT(*) FROM mobile_artifacts").fetchone()[0]
                assert_true(artifacts == expected["artifacts"],
                            f"real HTTP artifacts: {artifacts}")
                kinds = dict(con.execute(
                    "SELECT kind, COUNT(*) FROM mobile_artifacts GROUP BY kind"))
                for kind, count in expected["kinds"].items():
                    assert_true(kinds.get(kind) == count,
                                f"real HTTP kind {kind}: {kinds.get(kind)} != {count}")
            _, overview = api(base + f"/api/forensics/android/backup-overview?task_id={task_id}")
            assert_true(overview.get("manifest", {}).get("device") == expected_device,
                        f"real HTTP overview: {overview.get('manifest')}")
            counts = {row["kind"]: row["count"]
                      for row in overview.get("artifact_counts", [])}
            for kind, count in expected["kinds"].items():
                assert_true(counts.get(kind) == count,
                            f"real HTTP overview {kind}: {counts.get(kind)} != {count}")
            print(f"HTTP   real {expected['brand']} task artifacts={artifacts}")
        finally:
            server.terminate()
            server.wait(timeout=30)
            log.close()
    finally:
        stub.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyzer", required=True)
    parser.add_argument("--samples-root", default=None)
    args = parser.parse_args()
    analyzer = Path(args.analyzer).resolve()
    root = Path(args.samples_root or os.environ.get(
        "TRACELENS_THUNDERFORENSIC_SAMPLES", DEFAULT_SAMPLES))
    projects = {vendor: root / f"20261025{vendor}"
                for vendor in ("OPPO", "OnePlus", "VIVO")}
    if not all(path.is_dir() for path in projects.values()):
        print(f"SKIPPED: ThunderForensic samples not found under {root}")
        return

    with tempfile.TemporaryDirectory(prefix="thunder-real-") as temp:
        base = Path(temp)
        verify_oppo(analyzer, projects["OPPO"], base / "oppo")
        verify_oneplus(analyzer, projects["OnePlus"], base / "oneplus")
        verify_vivo(analyzer, projects["VIVO"], base / "vivo")
        verify_raw_tar(analyzer, projects["OPPO"], base / "oppo-raw")
        verify_real_http_task(analyzer, projects["OPPO"], base / "http", {
            "brand": "OPPO", "model": "PBEM00", "artifacts": 989,
            "kinds": {"application": 351, "file_inventory": 64}})
        verify_real_http_task(analyzer, projects["VIVO"], base / "http-vivo", {
            "brand": "vivo", "model": "V1824BA", "artifacts": 204690,
            "kinds": {"sms": 2079, "contact": 7005, "call_log": 5050,
                      "im_message": 49160}})
    print("ThunderForensic real-sample acceptance tests passed")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as error:
        print(f"FAILED: {error}", file=sys.stderr)
        sys.exit(1)
