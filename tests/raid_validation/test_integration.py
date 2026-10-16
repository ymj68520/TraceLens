# SPDX-License-Identifier: AGPL-3.0-or-later
"""Actual EWF decoding, filesystem readers and TraceLens CLI on synthetic data."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys

import pytest

from raid.core import RaidError, RaidSession
from raid.export import export_array, verify_package, write_json
from .fixtures import make_members

ROOT = Path(__file__).resolve().parents[2]


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(*args, **kwargs):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True,
                            timeout=kwargs.pop("timeout", 240), **kwargs)
    assert result.returncode == 0, (result.returncode, result.stderr[-1200:], result.stdout[-600:])
    return result


@pytest.mark.skipif(shutil.which("ewfacquire") is None, reason="open-source ewfacquire unavailable")
@pytest.mark.parametrize("compression", ["none", "deflate:fast"])
def test_explicit_ewf_segments_are_not_raid_member_order(tmp_path, compression):
    source = tmp_path / "inbox"
    members, expected = make_members(source, logical=bytes(range(256)) * 16384)
    ewf_members = []
    for i, member in enumerate(members):
        raw = source / member["files"][0]
        stem = source / f"acquisition-{i}"
        run("ewfacquire", "-u", "-q", "-c", compression, "-S", "1MiB", "-t", stem, raw)
        segments = sorted(source.glob(f"acquisition-{i}.E*"))
        if compression == "none":
            assert len(segments) >= 2, "fixture must actually exercise multi-segment EWF"
        ewf_members.append({"files": [p.name for p in segments]})
    with RaidSession(source, list(reversed(ewf_members))) as session:
        assert session.size == len(expected)
        assert session.read_at(0, len(expected)) == expected
        assert all(m["container"] == "EWF_E01" for m in session.members)
    missing = [dict(m) for m in ewf_members]
    if compression == "none":
        missing[0] = {"files": missing[0]["files"][:-1]}
        with pytest.raises(Exception):
            RaidSession(source, missing)


@pytest.mark.skipif(shutil.which("mke2fs") is None or shutil.which("fls") is None,
                    reason="open-source filesystem fixture tools unavailable")
def test_raid_export_to_actual_filesystem_and_file_content(tmp_path):
    tree = tmp_path / "tree"
    tree.mkdir()
    original = "已知取证内容：RAID 自动排序不是按输入顺序。\n".encode()
    (tree / "source.txt").write_bytes(original)
    logical = tmp_path / "filesystem.img"
    with logical.open("wb") as output:
        output.truncate(16 * 1024**2)
    run("mke2fs", "-q", "-F", "-t", "ext4", "-d", tree, logical)
    source = tmp_path / "inbox"
    members, expected = make_members(source, logical=logical.read_bytes())
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    with RaidSession(source, members) as session:
        exported = export_array(session, outputs, max_bytes=32 * 1024**2)
    package = Path(exported["package_directory"])
    listing = run("fls", "-r", package / "logical.img").stdout
    match = re.search(r"(?:r/r)\s+(\d+):\s+source\.txt", listing)
    assert match, listing
    content = subprocess.check_output(["icat", str(package / "logical.img"), match[1]])
    assert content == original
    assert verify_package(package)["logical_sha256"] == hashlib.sha256(expected).hexdigest()


@pytest.mark.skipif(not os.environ.get("TRACELENS_RAID_TEST_ANALYZER"),
                    reason="explicit isolated analyzer binary required")
def test_actual_tracelens_android_analysis_chain(tmp_path):
    analyzer = Path(os.environ["TRACELENS_RAID_TEST_ANALYZER"]).resolve(strict=True)
    sys.path.insert(0, str(ROOT / "tests" / "integration"))
    from test_android_container_cli_e2e import build_tree, counts, EXPECTED, assert_artifact_content
    tree = tmp_path / "tree"
    tree.mkdir()
    build_tree(tree)
    logical = tmp_path / "known-android.ext4"
    with logical.open("wb") as output:
        output.truncate(16 * 1024**2)
    run("mke2fs", "-q", "-F", "-t", "ext4", "-d", tree, logical)
    source = tmp_path / "inbox"
    members, expected = make_members(source, logical=logical.read_bytes())
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    with RaidSession(source, members) as session:
        exported = export_array(session, outputs, max_bytes=32 * 1024**2)
    package = Path(exported["package_directory"])
    # Prevent fallback to real .env/config/paths; this runtime fixture is local.
    work = tmp_path / "isolated-runtime"
    work.mkdir()
    (work / ".env").write_text(
        f"PROJECT_ROOT={work}\nDATA_DIR={work / 'data'}\n"
        "LLM_BASE_URL=\nFIELD_OUTBOUND_POLICY=disabled\n"
        "TRACELENS_FIELD_AUTH=enabled\nPYTHON_HTTP_PORT=19990\n"
    )
    databases = work / "databases"
    result = run(analyzer, package / "logical.img", "--android-analyze", "--no-ai",
                 "--db-dir", databases, cwd=work)
    artifacts = list(databases.glob("*android*.db")) or list(databases.glob("*_files.db"))
    # Preserve the existing CLI's unified *_files.db semantics. The HTTP Task
    # path's android.db is a different entry and is not claimed verified here.
    assert len(artifacts) == 1, (list(databases.iterdir()), result.stdout[-1200:])
    assert counts(artifacts[0]) == EXPECTED
    assert_artifact_content(artifacts[0])
    image_hash = hashlib.sha256(expected).hexdigest()
    assert exported["derived_image"]["sha256"] == image_hash
    files = list(databases.glob("*_files.db"))
    assert files
    with sqlite3.connect(f"file:{files[0]}?mode=ro", uri=True) as db:
        paths = [row[0] for row in db.execute("SELECT path FROM files")]
    assert any("mmssms.db" in path for path in paths)
    write_json(work / "raid-integration-result.json", {
        "status": "PASS", "actual_artifacts": EXPECTED, "expected_artifacts": EXPECTED,
        "input": "synthetic MD v1 RAID5, unordered complete members, EXT4 logical data",
        "logical_sha256": image_hash, "analyzer_sha256": sha256_file(analyzer),
        "warnings": ["REAL_SAMPLE_REQUIRED", "PRODUCTION_TASK_UI_NOT_CONNECTED",
                     "INVESTIGATION_MEMBER_TRACE_NOT_CONNECTED"],
    })


@pytest.mark.skipif(not os.environ.get("TRACELENS_RAID_MDADM"),
                    reason="explicit readonly metadata oracle required")
def test_independent_mdadm_examine(tmp_path):
    binary = Path(os.environ["TRACELENS_RAID_MDADM"]).resolve(strict=True)
    source = tmp_path / "inbox"
    members, expected = make_members(source)
    for member in members:
        result = run(binary, "--examine", "--config=/dev/null", source / member["files"][0])
        assert "raid5" in result.stdout
        assert "correct" in result.stdout
        assert "clean" in result.stdout
    with RaidSession(source, members) as session:
        assert session.size == len(expected)


def test_disk_space_failure_and_failed_marker_write(tmp_path, monkeypatch):
    import raid.export as exporter
    source = tmp_path / "inbox"
    members, _ = make_members(source)
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    original_usage = exporter.shutil.disk_usage
    monkeypatch.setattr(exporter.shutil, "disk_usage", lambda _: shutil._ntuple_diskusage(100, 99, 1))
    with RaidSession(source, members) as session:
        with pytest.raises(RaidError, match="INSUFFICIENT_OUTPUT_SPACE"):
            export_array(session, outputs, max_bytes=1024**2)
    assert not list(outputs.iterdir())
    monkeypatch.setattr(exporter.shutil, "disk_usage", original_usage)
    monkeypatch.setattr(exporter, "write_json", lambda *_: (_ for _ in ()).throw(OSError("synthetic full disk")))
    with RaidSession(source, members) as session:
        with pytest.raises(OSError):
            export_array(session, outputs, max_bytes=1024**2)
    assert not list(outputs.glob("*/logical.img"))
    assert not list(outputs.glob("*/raid_manifest.json"))
    assert list(outputs.glob("*/logical.img.partial"))


@pytest.mark.skipif(shutil.which("ewfacquire") is None, reason="ewfacquire unavailable")
def test_bad_ewf_chunk_checksum_is_rejected_not_zero_padded(tmp_path):
    from raid import vendor
    source = tmp_path / "inbox"
    members, _ = make_members(source)
    raw = source / members[0]["files"][0]
    run("ewfacquire", "-u", "-q", "-c", "none", "-t", source / "damaged", raw)
    file = source / "damaged.E01"
    reader = vendor.load("qnxprobe", "ewfprobe")
    with reader.open_ewf(str(file), segments=[str(file)]) as image:
        _, start, _, compressed = image._chunk_location(0)
        assert not compressed
    with file.open("r+b") as target:
        target.seek(start + 300)
        target.write(b"deliberately wrong checksum")
    selected = [{"files": [file.name]}, *members[1:]]
    with pytest.raises(RaidError, match="EWF_CHUNK_CHECKSUM_MISMATCH"):
        RaidSession(source, selected)


def test_full_source_distribution_is_offline_verifiable(tmp_path):
    import importlib.util
    import tarfile
    distribution = ROOT / "third_party" / "raid" / "sources.bundle.tar.gz"
    if not distribution.is_file():
        pytest.skip("create the pinned source distribution first")
    script = ROOT / "scripts" / "raid_vendor_sources.py"
    spec = importlib.util.spec_from_file_location("source_distribution", script)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    with tarfile.open(distribution, "r:gz") as archive:
        # Trusted local distribution, still reject archive traversal before use.
        for item in archive.getmembers():
            assert not Path(item.name).is_absolute() and ".." not in Path(item.name).parts
            assert not item.isdev() and not item.islnk()
        archive.extractall(tmp_path)
    tool.ROOT = tmp_path
    projects = json.loads((tmp_path / "sources.lock.json").read_text())["projects"]
    assert len(projects) == 9
    inventory = [tool.verify(project) for project in projects]
    # Frozen milestone artifact: this bundle predates dropping the upstream
    # test images from the checked-in snapshots.
    assert sum(p["files"] for p in inventory) == 2806
    assert (tmp_path / "upstream/nbdkit/common/replacements/win32/nbdkit-cat.h").is_file()
    assert (tmp_path / "upstream/nbdkit/filters/log/log.c").is_file()
