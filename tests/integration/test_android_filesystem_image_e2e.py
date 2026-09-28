"""Synthetic userdata EXT4/F2FS/RAW/E01 -> actual AndroidAnalyzer artifacts.

Only generated test images are written. Source evidence is never mounted or
modified. Requires mke2fs, mkfs.f2fs, sload.f2fs, sgdisk and ewfacquire.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys
import shutil
import sqlite3
import subprocess
import tempfile

from test_android_container_cli_e2e import build_tree, counts, EXPECTED, assert_artifact_content


def command(*args, timeout=180, **kwargs):
    result = subprocess.run([str(arg) for arg in args], text=True,
                            capture_output=True, timeout=timeout, **kwargs)
    if result.returncode:
        raise AssertionError(f"{args[0]} failed: {result.stderr[-1600:]} {result.stdout[-500:]}")
    return result


def build_userdata_tree(root: Path):
    logical = root / "logical"
    logical.mkdir()
    files = build_tree(logical)
    userdata = root / "userdata_files"
    for name, data in files.items():
        assert name.startswith("data/")
        target = userdata / name.removeprefix("data/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return userdata


def fixture_images(root: Path):
    tree = build_userdata_tree(root)
    ext = root / "userdata_ext4.img"
    command("truncate", "-s", "128M", ext)
    command("mke2fs", "-q", "-F", "-t", "ext4", "-L", "userdata", "-d", tree, ext)
    f2fs = root / "userdata_f2fs.img"
    command("truncate", "-s", "256M", f2fs)
    command("mkfs.f2fs", "-f", "-q", f2fs)
    command("sload.f2fs", "-f", tree, "-t", "/", "-T", "1700000000", f2fs)
    disk = root / "disk.img"
    command("truncate", "-s", "160M", disk)
    command("sgdisk", "-o", disk)
    command("sgdisk", "-n", "1:2048:+8M", "-c", "1:metadata",
            "-n", "2:0:+128M", "-c", "2:userdata", disk)
    sector = int(re.search(r"First sector: (\d+)", command("sgdisk", "-i", "2", disk).stdout).group(1))
    command("dd", f"if={ext}", f"of={disk}", "bs=512", f"seek={sector}", "conv=notrunc", "status=none")
    ewf_stem = root / "disk"
    command("ewfacquire", "-u", "-q", "-c", "deflate:fast", "-t", ewf_stem, disk,
            timeout=600)
    e01 = root / "disk.E01"
    assert e01.is_file()
    f2fs_disk = root / "disk_f2fs.img"
    command("truncate", "-s", "300M", f2fs_disk)
    command("sgdisk", "-o", f2fs_disk)
    command("sgdisk", "-n", "1:2048:+8M", "-c", "1:metadata",
            "-n", "2:0:+256M", "-c", "2:userdata", f2fs_disk)
    sector = int(re.search(r"First sector: (\d+)", command("sgdisk", "-i", "2", f2fs_disk).stdout).group(1))
    command("dd", f"if={f2fs}", f"of={f2fs_disk}", "bs=512", f"seek={sector}",
            "conv=notrunc", "status=none")
    command("ewfacquire", "-u", "-q", "-c", "deflate:fast", "-t",
            root / "disk_f2fs", f2fs_disk, timeout=600)
    f2fs_e01 = root / "disk_f2fs.E01"
    assert f2fs_e01.is_file()
    return {"ext4": ext, "f2fs": f2fs, "raw": disk, "e01": e01,
            "raw_f2fs": f2fs_disk, "e01_f2fs": f2fs_e01}


def locked_fixture(root: Path) -> Path:
    """SYNTHETIC_ENCRYPTION_METADATA_ONLY; never claim real FBE decryption.

    mkfs creates a volume with the encrypt feature. We set i_advise on the
    generated fixture's regular inodes to model inaccessible file content;
    this is not a copied phone acquisition or a ciphertext oracle.
    """
    target = root / "userdata_locked_f2fs.img"
    command("truncate", "-s", "256M", target)
    command("mkfs.f2fs", "-f", "-q", "-O", "encrypt", target)
    command("sload.f2fs", "-f", root / "userdata_files", "-t", "/",
            "-T", "1700000000", target)
    reader_root = Path(__file__).resolve().parents[2] / ".deps/qnxprobe"
    sys.path.insert(0, str(reader_root))
    import qnxprobe
    with target.open("r+b") as handle:
        walker = qnxprobe.F2fsWalker(handle, 0)
        for path, inode, mode, *_ in qnxprobe.walk_all(walker):
            if (mode & 0o170000) != 0o100000:
                continue
            node = walker.resolve(inode)
            handle.seek(node * walker.bs + 2)
            original = handle.read(1)
            handle.seek(node * walker.bs + 2)
            handle.write(bytes([original[0] | 0x04]))
    return target


def analyze(analyzer: Path, image: Path, root: Path):
    output = root / f"result_{image.name}"
    output.mkdir()
    result = command(analyzer, image, "--android-analyze", "--android-source",
                     "filesystem-image", "--no-ai", "--db-dir", output, timeout=240)
    database = output / f"{image.stem}_files.db"
    assert database.is_file(), result.stdout[-1000:]
    found = counts(database)
    assert_artifact_content(database)
    with sqlite3.connect(database) as db:
        provenance = db.execute("SELECT source_image_sha256, partition_start_offset, "
                                "filesystem_type, filesystem_object_id, filesystem_path, "
                                "normalized_android_path, file_sha256 "
                                "FROM android_filesystem_provenance").fetchall()
    assert any(row[5] == "data/data/com.android.providers.telephony/databases/mmssms.db"
               and len(row[6]) == 64 for row in provenance), provenance[:3]
    return found, provenance


def run(analyzer: Path):
    missing = [name for name in ("mke2fs", "mkfs.f2fs", "sload.f2fs", "sgdisk", "ewfacquire")
               if shutil.which(name) is None]
    if missing:
        raise RuntimeError(f"fixture tools missing: {missing}")
    with tempfile.TemporaryDirectory(prefix="tracelens_userdata_e2e_") as temp:
        root = Path(temp)
        images = fixture_images(root)
        results = {}
        for name, image in images.items():
            observed, provenance = analyze(analyzer, image, root)
            assert observed == EXPECTED, (name, observed, EXPECTED)
            results[name] = {"artifact_counts": observed,
                             "provenance_rows": len(provenance), "image_bytes": image.stat().st_size}
        assert results["ext4"]["artifact_counts"] == results["f2fs"]["artifact_counts"]
        locked = locked_fixture(root)
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python_service"))
        from httpserver.services.android_image_preflight import inspect
        assessment = inspect(locked)
        assert assessment["selected_partition"]["encryption"]["state"] == "LOCKED", assessment
        assert not assessment["ready"] and assessment["selected_partition"]["locked"]
        print({"locked_fixture": "SYNTHETIC_ENCRYPTION_METADATA_ONLY",
               "observed_status": "LOCKED", "reason": assessment["reason"]})
        print(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyzer", type=Path, required=True)
    args = parser.parse_args()
    run(args.analyzer.resolve(strict=True))
