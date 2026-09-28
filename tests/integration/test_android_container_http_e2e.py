"""Synthetic AOSP sparse/super -> verified HTTP Task production chains."""

import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from test_android_container_cli_e2e import EXPECTED, counts, assert_artifact_content
from test_android_filesystem_image_e2e import fixture_images
from httpserver.services import evidence_preflight as preflight
from httpserver.services.android_sparse_image import file_sha256
from httpserver.services.android_lp_image import tool_root


def cmd(*args, timeout=600):
    run = subprocess.run([str(arg) for arg in args], capture_output=True, text=True,
                         timeout=timeout, check=False)
    assert run.returncode == 0, (args, run.stderr[-1000:], run.stdout[-300:])


def json_request(url, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=body,
        headers={"Content-Type": "application/json"} if body else {})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def make_super(root: Path) -> tuple[Path, dict]:
    inputs = {}
    for name, letter in (("system_a", b"S"), ("vendor_a", b"V")):
        image = root / f"{name}.img"
        with image.open("wb") as sink:
            sink.write(letter * 4096)
            sink.truncate(8 * 1024 * 1024)
        inputs[name] = image
    product_dir = root / "product_tree"
    product_dir.mkdir()
    (product_dir / "build.txt").write_text("synthetic EROFS partition\n")
    product = root / "product_a.img"
    cmd("mkfs.erofs", "--quiet", product, product_dir)
    cmd("truncate", "-s", "8M", product)
    inputs["product_a"] = product
    super_raw = root / "super.raw"
    args = [tool_root() / "bin/lpmake", "--metadata-size", "65536",
            "--metadata-slots", "2", "--device-size", "67108864",
            "--group", "main_a:50331648"]
    for name, image in inputs.items():
        args += ["--partition", f"{name}:readonly:8388608:main_a",
                 "--image", f"{name}={image}"]
    cmd(*args, "--output", super_raw)
    return super_raw, {name: file_sha256(path) for name, path in inputs.items()}


def make_full_disk(root: Path, super_raw: Path) -> tuple[Path, Path]:
    disk = root / "disk_super.img"
    cmd("truncate", "-s", "96M", disk)
    cmd("sgdisk", "-o", disk)
    cmd("sgdisk", "-n", "1:2048:+64M", "-c", "1:super", disk)
    cmd("dd", f"if={super_raw}", f"of={disk}", "bs=512", "seek=2048",
        "conv=notrunc", "status=none")
    cmd("ewfacquire", "-u", "-q", "-c", "deflate:fast",
        "-t", root / "disk_super", disk)
    e01 = root / "disk_super.E01"
    assert e01.is_file()
    return disk, e01


def wait_preflight(root: Path, data_dir: Path, source: Path, *, selected_slot: int = 0):
    preflight.evidence_inbox = lambda: root.resolve()
    preflight.job_root = lambda: data_dir / "evidence_preflight"
    candidate = next(item for item in preflight.list_candidates() if item["name"] == source.name)
    job_id = preflight.start_job(candidate["id"], full_hash=True,
                                 selected_slot=selected_slot)["id"]
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        job = preflight.get_job(job_id)
        if job["status"] not in {"queued", "running"}:
            assert job["status"] == "completed" and job["integrity_status"] == "verified", job
            return job
        time.sleep(0.1)
    raise AssertionError("container preflight timed out")


def wait_task(base, task_id):
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        _, task = json_request(base + "/api/tasks/" + task_id)
        if str(task.get("status", "")).lower() in {"completed", "failed", "cancelled"}:
            return task
        time.sleep(0.2)
    raise AssertionError("container Task timed out")


def create_task(base, job, source, *, mode):
    body = {"image_path": str(source), "android_source": mode,
            "scenarios": ["android"], "platform_analyze": True,
            "llm_analyze": False, "preflight_job_id": job["id"],
            "preflight_source_sha256": job["sha256"],
            "preflight_detected_kind": job["detected"]["kind"]}
    if mode == "android-container":
        body.update(preflight_plan_sha256=job["container"]["plan_sha256"],
                    preflight_selected_slot=job["selected_slot"])
    code, created = json_request(base + "/api/tasks", body)
    assert code == 201, (code, created, source)
    task = wait_task(base, created["id"])
    assert str(task["status"]).lower() == "completed", task
    return task


def artifact_rows(database):
    with sqlite3.connect(database) as connection:
        return {name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                for name in EXPECTED}


def coverage_rows(database):
    with sqlite3.connect(database) as connection:
        return connection.execute("SELECT artifact_kind,source_path,status FROM android_source_coverage "
                                  "ORDER BY artifact_kind,source_path").fetchall()


def run(analyzer: Path):
    with tempfile.TemporaryDirectory(prefix="tracelens_container_http_e2e_") as directory:
        root = Path(directory)
        runtime = root / "runtime"; runtime.mkdir()
        images = fixture_images(root)
        sparse = {}
        for kind in ("ext4", "f2fs"):
            target = root / f"userdata_{kind}.sparse"
            cmd("img2simg", images[kind], target)
            sparse[kind] = target
        super_raw, source_hashes = make_super(root)
        super_sparse = root / "super.sparse"
        cmd("img2simg", super_raw, super_sparse)
        disk, e01 = make_full_disk(root, super_raw)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]
        log = root / "cpp.log"
        env = dict(os.environ, DATA_DIR=str(runtime), LLM_ENABLED="false", GRAPHITI_ENABLED="false")
        with log.open("w", encoding="utf-8") as output:
            server = subprocess.Popen([str(analyzer), "--http-server", str(port)],
                                      env=env, stdout=output, stderr=subprocess.STDOUT)
            try:
                base = f"http://127.0.0.1:{port}"
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    if server.poll() is not None:
                        raise AssertionError("isolated C++ server exited")
                    try:
                        if json_request(base + "/api/system/health")[0] == 200:
                            break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise AssertionError("isolated C++ server not healthy")

                comparison = {}
                for kind in ("ext4", "f2fs"):
                    raw_job = wait_preflight(root, runtime, images[kind])
                    raw_task = create_task(base, raw_job, images[kind], mode="filesystem-image")
                    sparse_job = wait_preflight(root, runtime, sparse[kind])
                    assert sparse_job["detected"]["kind"] == "android_sparse_userdata", sparse_job
                    sparse_task = create_task(base, sparse_job, sparse[kind], mode="android-container")
                    raw_db = Path(raw_task["output_files_db"])
                    sparse_db = Path(sparse_task["output_files_db"])
                    assert artifact_rows(raw_db) == artifact_rows(sparse_db) == EXPECTED
                    assert_artifact_content(raw_db)
                    assert_artifact_content(sparse_db)
                    assert coverage_rows(raw_db) == coverage_rows(sparse_db)
                    with sqlite3.connect(raw_db) as connection:
                        raw_provenance = connection.execute(
                            "SELECT COUNT(*) FROM android_filesystem_provenance").fetchone()[0]
                    with sqlite3.connect(sparse_db) as connection:
                        sparse_provenance = connection.execute(
                            "SELECT COUNT(*) FROM android_filesystem_provenance").fetchone()[0]
                        bodies = connection.execute("SELECT body FROM sms_messages ORDER BY date").fetchall()
                    assert raw_provenance == sparse_provenance == 6
                    assert len(bodies) == 2 and bodies[1][0] == "fixture-message-2"
                    manifest = json.loads((sparse_db.parent / "android_normalization_manifest.json").read_text())
                    assert manifest["normalized_kind"] == "userdata"
                    assert manifest["derived_sha256"] == file_sha256(images[kind])
                    assert manifest["steps"][1]["operation"] == "UNSPARSE"
                    assert manifest["steps"][-1]["operation"] == "ARTIFACT_ANALYSIS"
                    assert manifest["steps"][-1]["output_sha256"] == file_sha256(sparse_db)
                    comparison[kind] = {"counts": artifact_rows(sparse_db),
                                        "provenance": sparse_provenance,
                                        "expanded_size": manifest["performance"]["expanded_size"],
                                        "conversion_seconds": manifest["performance"]["conversion_seconds"]}

                super_results = {}
                for label, source in (("raw_super", super_raw), ("sparse_super", super_sparse),
                                      ("full_raw", disk), ("full_e01", e01)):
                    job = wait_preflight(root, runtime, source)
                    assert job["detected"]["adapter"] == "android-container", (label, job)
                    task = create_task(base, job, source, mode="android-container")
                    assert "USERDATA_NOT_PRESENT" in task.get("message", ""), task
                    database = Path(task["output_files_db"])
                    with sqlite3.connect(database) as connection:
                        status = connection.execute("SELECT status FROM android_source_coverage "
                                                    "WHERE artifact_kind='userdata'").fetchone()[0]
                    assert status == "NOT_PRESENT_IN_SOURCE"
                    manifest = json.loads((database.parent / "android_normalization_manifest.json").read_text())
                    assert manifest["normalized_kind"] == "super"
                    assert manifest["super_inventory"]["metadata_slot_count"] == 2
                    assert manifest["super_inventory"]["active_slot"] == "ACTIVE_SLOT_UNKNOWN"
                    provenance = {item["logical_partition_name"]: item["derived_partition_sha256"]
                                  for item in manifest["partition_provenance"]}
                    assert provenance == source_hashes, (label, provenance, source_hashes)
                    product = next(item for item in manifest["partition_provenance"]
                                   if item["logical_partition_name"] == "product_a")
                    assert product["filesystem_type"] == "EROFS"
                    assert any(step["status"] == "UNSUPPORTED_FILESYSTEM" for step in manifest["steps"])
                    super_results[label] = {"partitions": list(provenance),
                        "partition_hashes": provenance,
                        "extracted_bytes": manifest["performance"]["extracted_bytes"],
                        "metadata_parse_seconds": manifest["performance"]["metadata_parse_seconds"],
                        "extraction_seconds": manifest["performance"]["extraction_seconds"]}
                    if label in {"full_raw", "full_e01"}:
                        assert manifest["steps"][1]["operation"] == "SUPER_PARTITION_COPY"
                        assert manifest["steps"][1]["parameters"]["partition_offset"] == 1048576
                slot_one_job = wait_preflight(root, runtime, super_raw, selected_slot=1)
                assert slot_one_job["container"]["selected_slot"] == 1
                slot_one_task = create_task(base, slot_one_job, super_raw, mode="android-container")
                slot_one_manifest = json.loads((Path(slot_one_task["output_files_db"]).parent /
                                                "android_normalization_manifest.json").read_text())
                assert slot_one_manifest["selected_slot"] == 1
                assert slot_one_manifest["active_slot"] == "ACTIVE_SLOT_UNKNOWN"
                old = wait_preflight(root, runtime, sparse["ext4"])
                with sparse["ext4"].open("ab") as sink:
                    sink.write(b"changed")
                code, rejected = json_request(base + "/api/tasks", {
                    "image_path": str(sparse["ext4"]), "android_source": "android-container",
                    "preflight_job_id": old["id"], "preflight_source_sha256": old["sha256"],
                    "preflight_detected_kind": old["detected"]["kind"],
                    "preflight_plan_sha256": old["container"]["plan_sha256"],
                    "preflight_selected_slot": 0})
                assert code == 409 and rejected["error_code"] == "EVIDENCE_CHANGED_AFTER_PREFLIGHT"
                print({"sparse_userdata": comparison, "super": super_results,
                       "changed_source": "HTTP 409"})
            except Exception:
                output.flush()
                print(log.read_text(encoding="utf-8", errors="replace")[-4000:])
                raise
            finally:
                server.terminate()
                try: server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill(); server.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyzer", type=Path, required=True)
    args = parser.parse_args()
    run(args.analyzer.resolve(strict=True))
