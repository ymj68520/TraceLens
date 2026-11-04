"""Unit tests for iOS logical-backup preflight triage."""

from __future__ import annotations

import plistlib
import sqlite3
from pathlib import Path

import pytest

from httpserver.services import ios_backup_preflight


def _make_backup(root: Path, *, encrypted: bool = False, files=None,
                 with_files_table: bool = True, app_count: int = 0) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    manifest_plist = {
        "IsEncrypted": encrypted,
        "Version": "10.0",
        "Date": "2023-10-10T07:41:57Z",
        "Lockdown": {
            "ProductType": "iPhone10,3",
            "ProductVersion": "16.5",
            "BuildVersion": "20F66",
            "UniqueDeviceID": "d5747fae8f4ddba485f17710026bd6bff268acb0",
            "SerialNumber": "G6VWVGSXJCLF",
        },
        "Applications": {f"com.example.app{i}": {} for i in range(app_count)},
    }
    with (root / "Manifest.plist").open("wb") as handle:
        plistlib.dump(manifest_plist, handle)

    connection = sqlite3.connect(root / "Manifest.db")
    if with_files_table:
        connection.execute(
            "CREATE TABLE Files (fileID TEXT PRIMARY KEY, domain TEXT, "
            "relativePath TEXT, flags INTEGER, file BLOB)")
        for file_id, domain, relative_path, flags in (files or []):
            connection.execute(
                "INSERT INTO Files(fileID, domain, relativePath, flags) VALUES(?,?,?,?)",
                (file_id, domain, relative_path, flags))
    else:
        connection.execute("CREATE TABLE Other(value INTEGER)")
    connection.commit()
    connection.close()
    return root


def _write_shard(root: Path, file_id: str, payload: bytes = b"SQLite format 3\x00") -> None:
    shard = root / file_id[:2] / file_id
    shard.parent.mkdir(parents=True, exist_ok=True)
    shard.write_bytes(payload)


def test_locates_backup_nested_two_levels(tmp_path: Path) -> None:
    backup = _make_backup(tmp_path / "case name" / "UDID",
                          files=[("a" * 40, "HomeDomain", "Library/SMS/sms.db", 1)])
    found = ios_backup_preflight.locate_backup_root(tmp_path)
    assert found == backup


def test_reports_plaintext_backup_with_key_artifacts(tmp_path: Path) -> None:
    backup = _make_backup(tmp_path / "UDID", files=[
        ("a" * 40, "HomeDomain", "Library/SMS/sms.db", 1),
        ("b" * 40, "HomeDomain", "Library/AddressBook/AddressBook.sqlitedb", 1),
    ])
    _write_shard(backup, "a" * 40)
    _write_shard(backup, "b" * 40)

    result = ios_backup_preflight.inspect(tmp_path)

    assert result["kind"] == "ios_backup"
    assert result["ready"] is True
    assert result["encryption_status"] == "none"
    assert result["device"]["product_type"] == "iPhone10,3"
    assert result["device"]["unique_device_id"] == "d5747fae8f4ddba485f17710026bd6bff268acb0"
    assert result["artifacts_present"] == 2
    assert result["artifacts"]["sms"]["present"] is True
    assert result["artifacts"]["sms"]["size"] == 16
    assert result["artifacts"]["call_logs"]["present"] is False
    assert result["manifest_sha256"]


def test_encrypted_backup_is_locked_not_ready(tmp_path: Path) -> None:
    _make_backup(tmp_path / "UDID", encrypted=True)
    result = ios_backup_preflight.inspect(tmp_path)
    assert result["kind"] == "ios_backup_encrypted"
    assert result["ready"] is False
    assert result["encryption_status"] == "locked"
    assert result["reason"] == "encrypted_backup_requires_password"


def test_missing_files_table_is_unsupported(tmp_path: Path) -> None:
    _make_backup(tmp_path / "UDID", with_files_table=False)
    result = ios_backup_preflight.inspect(tmp_path)
    assert result["kind"] == "ios_backup_unsupported"
    assert result["reason"] == "manifest_missing_files_table"
    assert result["ready"] is False


def test_non_backup_directory_is_unknown(tmp_path: Path) -> None:
    (tmp_path / "random").mkdir()
    result = ios_backup_preflight.inspect(tmp_path)
    assert result["kind"] == "unknown_directory"
    assert result["ready"] is False


def test_shard_missing_on_disk_marks_artifact_absent(tmp_path: Path) -> None:
    _make_backup(tmp_path / "UDID", files=[
        ("c" * 40, "HomeDomain", "Library/SMS/sms.db", 1)])
    # Manifest lists the file but the shard was never copied.
    result = ios_backup_preflight.inspect(tmp_path)
    assert result["artifacts"]["sms"]["present"] is False
    assert result["artifacts_present"] == 0
    assert result["ready"] is False
    assert "no_parsable_artifact_found" == result["reason"]


def test_apple_nanoseconds_convert_to_expected_unix() -> None:
    # 715157772646219008 ns since 2001-01-01 == 2023-08-31T06:56:12Z
    assert ios_backup_preflight.apple_nanoseconds_to_unix(715157772646219008) == 1693464972


def test_apple_seconds_convert_to_expected_unix() -> None:
    assert ios_backup_preflight.apple_seconds_to_unix(715157772) == 1693464972


def test_zero_and_negative_timestamps_are_zero() -> None:
    assert ios_backup_preflight.apple_nanoseconds_to_unix(0) == 0
    assert ios_backup_preflight.apple_nanoseconds_to_unix(-5) == 0
    assert ios_backup_preflight.apple_seconds_to_unix(0) == 0


def test_detect_apple_epoch_unit_classifies_magnitudes() -> None:
    assert ios_backup_preflight.detect_apple_epoch_unit(715157772646219008) == "apple_epoch_ns"
    assert ios_backup_preflight.detect_apple_epoch_unit(715157772) == "apple_epoch_s"
    assert ios_backup_preflight.detect_apple_epoch_unit(1693464972) == "unix_s"
