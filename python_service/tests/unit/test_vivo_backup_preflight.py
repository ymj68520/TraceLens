"""Unit tests for vivo (iQOO) backup preflight triage.

Fixtures synthesise the two parts a real backup has: a ``.backup`` JSON header
and a LevelDB ``db/`` index. Building the LevelDB through plyvel keeps the test
independent of any real evidence.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest

plyvel = pytest.importorskip("plyvel")

from httpserver.services import vivo_backup_preflight


def _write_header(root: Path, *, model="vivo iQOO", encrypted=False, success=True) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".backup").write_text(json.dumps({
        "model": model,
        "createTime": 1793257658334,
        "encrypted": encrypted,
        "backupPackageVer": 2,
        "success": success,
    }), encoding="utf-8")


def _build_index(root: Path, entries: dict[str, object]) -> None:
    db_dir = root / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    db = plyvel.DB(str(db_dir), create_if_missing=True)
    for key, value in entries.items():
        db.put(key.encode(), json.dumps(value).encode())
    db.close()


def _payload(root: Path, file_hash: str, size: int = 16) -> None:
    (root / file_hash).write_bytes(b"x" * size)


def _make_backup(tmp_path: Path, entries: dict[str, object], *, header=None) -> Path:
    root = tmp_path / "case" / "vivo iQOO 20261029_150738"
    _write_header(root, **(header or {}))
    _build_index(root, entries)
    return root


def test_locates_wrapped_backup_directory(tmp_path: Path) -> None:
    root = _make_backup(tmp_path, {})
    found = vivo_backup_preflight.locate_backup_root(tmp_path)
    assert found == root


def test_reports_file_categories_and_counts(tmp_path: Path) -> None:
    entries = {
        "album": {"filename": "album", "hash": "a" * 40, "size": 100, "count": 2, "innerstoragepath": "/storage/emulated/0"},
        "album_0000000_" + "1" * 40: {
            "filename": "storage/emulated/0/DCIM/Camera/IMG_1.jpg",
            "hash": "1" * 40, "size": 3403363, "mtime": 1573115211000,
        },
        "album_0000001_" + "2" * 40: {
            "filename": "storage/emulated/0/DCIM/Camera/IMG_2.jpg",
            "hash": "2" * 40, "size": 3400798, "mtime": 1573115212000,
        },
        "sms": {"name": "信息", "data_type": 2, "count": 2331, "size": 4662000},
    }
    root = _make_backup(tmp_path, entries)
    _payload(root, "1" * 40)
    _payload(root, "2" * 40)

    result = vivo_backup_preflight.inspect(tmp_path)

    assert result["kind"] == "vivo_backup"
    assert result["ready"] is True
    assert result["model"] == "vivo iQOO"
    assert result["backup_package_version"] == 2
    assert result["item_total"] == 2
    assert result["item_counts"] == {"album": 2}
    assert result["payload"]["files_present"] == 2
    # Structured categories are reported separately and marked as not stored
    # as files, so no reader can mistake the phone-side count for backup rows.
    record = {row["key"]: row for row in result["record_categories"]}
    assert record["sms"]["count"] == 2331
    assert record["sms"]["stored_as_files"] is False


def test_xor_obfuscation_is_reported_not_hidden(tmp_path: Path) -> None:
    entries = {
        "xor_obfuscated": True,
        "album": {"filename": "album", "hash": "a" * 40, "size": 10, "count": 1},
        "album_0000000_" + "1" * 40: {
            "filename": "storage/emulated/0/DCIM/Camera/x.jpg", "hash": "1" * 40, "size": 10,
        },
    }
    root = _make_backup(tmp_path, entries)
    _payload(root, "1" * 40)

    result = vivo_backup_preflight.inspect(tmp_path)

    assert result["payload"]["obfuscated"] is True
    assert result["payload"]["readable"] is False
    assert "payload_xor_obfuscated" in result["warnings"]


def test_encrypted_backup_is_locked(tmp_path: Path) -> None:
    root = _make_backup(tmp_path, {}, header={"encrypted": True})
    result = vivo_backup_preflight.inspect(tmp_path)
    assert result["kind"] == "vivo_backup_encrypted"
    assert result["ready"] is False
    assert result["encryption_status"] == "locked"


def test_missing_payload_files_are_counted(tmp_path: Path) -> None:
    entries = {
        "album": {"filename": "album", "hash": "a" * 40, "size": 10, "count": 2},
        "album_0000000_" + "1" * 40: {"filename": "a.jpg", "hash": "1" * 40, "size": 10},
        "album_0000001_" + "2" * 40: {"filename": "b.jpg", "hash": "2" * 40, "size": 10},
    }
    root = _make_backup(tmp_path, entries)
    _payload(root, "1" * 40)

    result = vivo_backup_preflight.inspect(tmp_path)
    assert result["payload"]["files_present"] == 1
    assert result["payload"]["files_missing"] == 1
    assert any(w.startswith("payload_files_missing") for w in result["warnings"])


def test_application_entries_are_collected(tmp_path: Path) -> None:
    entries = {
        "app": {"name": "应用", "data_type": 3, "count": 2, "size": 100},
        "app_com.example.one.apk": {
            "filename": "app_com.example.one.apk", "hash": "3" * 40, "size": 55,
            "pkg": "com.example.one", "appName": "One", "version_name": "1.0",
            "version_code": 10, "with_data": True,
        },
        "app_com.example.one.data": {
            "filename": "app_com.example.one.data", "hash": "4" * 40, "size": 66,
        },
    }
    root = _make_backup(tmp_path, entries)
    _payload(root, "3" * 40)
    _payload(root, "4" * 40)

    result = vivo_backup_preflight.inspect(tmp_path)
    assert result["application_count"] == 1
    kinds = sorted(app["kind"] for app in result["applications"])
    assert kinds == ["apk", "data"]
    apk = next(a for a in result["applications"] if a["kind"] == "apk")
    assert apk["app_name"] == "One"
    assert apk["version_name"] == "1.0"


def test_non_backup_directory_is_unknown(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    result = vivo_backup_preflight.inspect(tmp_path)
    assert result["kind"] == "unknown_directory"
    assert result["ready"] is False


def test_header_only_without_index_is_not_ready(tmp_path: Path) -> None:
    root = tmp_path / "UDID"
    _write_header(root)
    result = vivo_backup_preflight.inspect(tmp_path)
    # Header present but db/ missing -> locate_backup_root rejects it entirely.
    assert result["kind"] == "unknown_directory"
    assert result["ready"] is False
