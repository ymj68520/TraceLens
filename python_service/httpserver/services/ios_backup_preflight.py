"""Bounded, read-only triage for iOS (iTunes/Finder) logical backups.

An iOS backup is a directory holding ``Manifest.plist`` + ``Manifest.db`` plus
two-character shard directories whose files are named by the SHA-1 of their
logical path. ``Manifest.db``'s ``Files`` table maps ``fileID`` (the shard file
name) to ``domain`` + ``relativePath``.

This module only identifies the layout and reports whether the backup is
encrypted. It never decrypts, never writes, and never claims that any artifact
has been parsed. The analysis adapter re-reads the same files independently.
"""

from __future__ import annotations

import hashlib
import os
import plistlib
import sqlite3
import stat
from pathlib import Path

# A backup holds thousands of tiny files; bound every scan so a hostile or
# enormous tree cannot stall preflight.
MAX_SHARD_ENTRIES = 50_000
MAX_MANIFEST_BYTES = 512 * 1024 * 1024
MAX_PLIST_BYTES = 32 * 1024 * 1024
# Extracted archives nest the backup as extract/<case>/<UDID>/; two levels of
# wrapper search covers that without walking an arbitrary tree.
MAX_WRAPPER_DEPTH = 2

# Domains that carry the artifacts the analyzer understands.
KEY_DOMAINS = {
    "HomeDomain": "device home (SMS, address book, Safari, notes)",
    "CameraRollDomain": "camera roll media",
    "MediaDomain": "media library",
    "RootDomain": "root-level device files",
}

# Files the analyzer will attempt to parse, as (domain, relativePath) pairs.
KEY_ARTIFACTS = {
    "sms": ("HomeDomain", "Library/SMS/sms.db"),
    "contacts": ("HomeDomain", "Library/AddressBook/AddressBook.sqlitedb"),
    "call_logs": ("HomeDomain", "Library/CallHistoryDB/CallHistory.storedata"),
    "safari": ("HomeDomain", "Library/Safari/History.db"),
    "notes": ("HomeDomain", "Library/Notes/notes.sqlite"),
    "calendar": ("HomeDomain", "Library/Calendar/Calendar.sqlitedb"),
}

_APPLE_EPOCH_OFFSET = 978307200  # seconds between 1970-01-01 and 2001-01-01


def _open_readonly(path: Path) -> sqlite3.Connection:
    """Open a SQLite database without creating files or taking write locks."""
    uri = "file:" + str(path).replace("?", "%3f").replace("#", "%23") + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _safe_regular_file(path: Path, limit: int) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and info.st_size <= limit


def _read_plist(path: Path) -> dict:
    if not _safe_regular_file(path, MAX_PLIST_BYTES):
        return {}
    try:
        with path.open("rb") as source:
            value = plistlib.load(source)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def locate_backup_root(path: Path) -> Path | None:
    """Find the directory holding Manifest.plist + Manifest.db.

    Accepts the backup directory itself, or a wrapper tree that contains
    exactly one backup. Extracted archives commonly nest it one or two levels
    deep (``extract/<case name>/<UDID>/``), so the search is bounded to
    MAX_WRAPPER_DEPTH levels instead of assuming a fixed shape.
    """
    direct = _backup_marker(path)
    if direct is not None:
        return direct

    found: list[Path] = []
    frontier = [path]
    for _ in range(MAX_WRAPPER_DEPTH):
        next_frontier: list[Path] = []
        for parent in frontier:
            try:
                children = [child for child in parent.iterdir()
                            if child.is_dir() and not child.is_symlink()]
            except OSError:
                continue
            for child in children:
                if _backup_marker(child) is not None:
                    found.append(child)
                else:
                    next_frontier.append(child)
        if found:
            break
        frontier = next_frontier
        if not frontier:
            break

    if not found:
        return None
    # Multiple backups under one wrapper: pick the shallowest, then the first
    # by name so the choice is deterministic and reportable.
    found.sort(key=lambda item: (len(item.parts), str(item)))
    return found[0]


def _backup_marker(candidate: Path) -> Path | None:
    try:
        if (candidate / "Manifest.plist").is_file() and (candidate / "Manifest.db").is_file():
            return candidate
    except OSError:
        return None
    return None


def inspect(path: Path) -> dict:
    """Identify an iOS logical backup and report what it contains.

    Returns a dict with ``kind`` one of ``ios_backup``, ``ios_backup_encrypted``,
    ``ios_backup_unsupported``, or ``unknown_directory``. ``ready`` is only true
    when the analyzer can proceed.
    """
    root = locate_backup_root(path)
    if root is None:
        return {"kind": "unknown_directory", "ready": False,
                "reason": "no_manifest_plist_and_manifest_db"}

    manifest_plist = _read_plist(root / "Manifest.plist")
    if not manifest_plist:
        return {"kind": "ios_backup_unsupported", "ready": False,
                "backup_root": str(root), "reason": "manifest_plist_unreadable"}

    encrypted = bool(manifest_plist.get("IsEncrypted"))
    if encrypted:
        return {
            "kind": "ios_backup_encrypted",
            "ready": False,
            "backup_root": str(root),
            "reason": "encrypted_backup_requires_password",
            "encryption_status": "locked",
            "lockdown": _device_summary(manifest_plist),
        }

    manifest_db = root / "Manifest.db"
    if not _safe_regular_file(manifest_db, MAX_MANIFEST_BYTES):
        return {"kind": "ios_backup_unsupported", "ready": False,
                "backup_root": str(root), "reason": "manifest_db_unreadable"}

    try:
        connection = _open_readonly(manifest_db)
    except sqlite3.Error:
        return {"kind": "ios_backup_unsupported", "ready": False,
                "backup_root": str(root), "reason": "manifest_db_not_sqlite"}
    try:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "Files" not in tables:
            return {"kind": "ios_backup_unsupported", "ready": False,
                    "backup_root": str(root), "reason": "manifest_missing_files_table"}
        columns = {row[1] for row in connection.execute("PRAGMA table_info(Files)")}
        required = {"fileID", "domain", "relativePath", "flags"}
        if not required <= columns:
            return {"kind": "ios_backup_unsupported", "ready": False,
                    "backup_root": str(root), "reason": "manifest_files_schema_mismatch"}

        total = connection.execute("SELECT COUNT(*) FROM Files").fetchone()[0]
        file_rows = connection.execute(
            "SELECT COUNT(*) FROM Files WHERE flags = 1").fetchone()[0]
        directory_rows = connection.execute(
            "SELECT COUNT(*) FROM Files WHERE flags = 2").fetchone()[0]
        domain_rows = connection.execute(
            "SELECT domain, COUNT(*) FROM Files WHERE flags = 1 "
            "GROUP BY domain ORDER BY COUNT(*) DESC").fetchall()

        artifacts = {}
        for name, (domain, relative_path) in KEY_ARTIFACTS.items():
            row = connection.execute(
                "SELECT fileID FROM Files WHERE domain = ? AND relativePath = ? "
                "AND flags = 1", (domain, relative_path)).fetchone()
            if row is None:
                artifacts[name] = {"present": False, "source_path": f"{domain}/{relative_path}"}
                continue
            file_id = row[0]
            shard = root / file_id[:2] / file_id
            artifacts[name] = {
                "present": shard.is_file(),
                "source_path": f"{domain}/{relative_path}",
                "file_id": file_id,
                "size": shard.stat().st_size if shard.is_file() else 0,
            }
    except sqlite3.Error:
        return {"kind": "ios_backup_unsupported", "ready": False,
                "backup_root": str(root), "reason": "manifest_db_query_failed"}
    finally:
        connection.close()

    present = sum(1 for value in artifacts.values() if value.get("present"))
    warnings = []
    if present == 0:
        warnings.append("no_key_artifact_present")
    if manifest_plist.get("Version") is None:
        warnings.append("manifest_plist_missing_version")

    return {
        "kind": "ios_backup",
        "ready": present > 0,
        "backup_root": str(root),
        "encryption_status": "none",
        "reason": None if present else "no_parsable_artifact_found",
        "backup_version": str(manifest_plist.get("Version") or ""),
        "device": _device_summary(manifest_plist),
        "application_count": len(manifest_plist.get("Applications") or {}),
        "total_entries": total,
        "file_entries": file_rows,
        "directory_entries": directory_rows,
        "domains": [{"domain": domain, "files": count} for domain, count in domain_rows[:50]],
        "key_domains": {name: detail for name, detail in KEY_DOMAINS.items()
                        if any(row[0] == name for row in domain_rows)},
        "artifacts": artifacts,
        "artifacts_present": present,
        "manifest_sha256": _sha256(manifest_db),
        "manifest_plist_sha256": _sha256(root / "Manifest.plist"),
        "warnings": warnings,
    }


def _device_summary(manifest_plist: dict) -> dict:
    lockdown = manifest_plist.get("Lockdown")
    if not isinstance(lockdown, dict):
        return {}
    return {
        "product_type": lockdown.get("ProductType"),
        "product_version": lockdown.get("ProductVersion"),
        "build_version": lockdown.get("BuildVersion"),
        "unique_device_id": lockdown.get("UniqueDeviceID"),
        "serial_number": lockdown.get("SerialNumber"),
        "imei": lockdown.get("IMEI"),
    }


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def apple_nanoseconds_to_unix(value: int) -> int:
    """Convert an Apple-epoch nanosecond stamp to Unix seconds.

    ``sms.db`` and most Core Data stores keep nanoseconds since 2001-01-01, so
    a 2023 message reads ~7.15e17.
    """
    if not isinstance(value, int) or value <= 0:
        return 0
    return value // 10**9 + _APPLE_EPOCH_OFFSET


def apple_seconds_to_unix(value: int) -> int:
    """Convert an Apple-epoch second stamp to Unix seconds.

    A handful of stores keep seconds since 2001-01-01 instead; a 2023 value
    reads ~7.15e8.
    """
    if not isinstance(value, int) or value <= 0:
        return 0
    return value + _APPLE_EPOCH_OFFSET


def detect_apple_epoch_unit(value: int) -> str:
    """Classify an Apple/Core Data timestamp by magnitude.

    Returns ``apple_epoch_ns``, ``apple_epoch_s`` or ``unix_s``. Callers that
    know the column should convert explicitly instead of relying on this.
    """
    if not isinstance(value, int) or value <= 0:
        return "unix_s"
    if value > 10**14:
        return "apple_epoch_ns"
    # Apple-epoch seconds for 2001-2039 span 0..1.2e9; Unix seconds for the
    # same era start at 9.8e8. 1.2e9 is the least-wrong single cut-off.
    if value < 1_200_000_000:
        return "apple_epoch_s"
    return "unix_s"
