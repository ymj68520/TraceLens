"""Bounded, read-only triage for a vivo (iQOO) PC-assistant phone backup.

A vivo backup produced by 互传 / 手机助手 has two parts:

* ``.backup`` — a one-line JSON header: model, createTime, ``encrypted``,
  ``backupPackageVer``, ``success``.
* ``db/`` — a LevelDB store that is the backup's **index**. Keys are either
  category summaries (``sms``, ``contact``, ``call``, ...) or per-item records
  named ``<category>_<7-digit index>_<sha1>``. Each per-item value is JSON with
  the original ``filename``, content ``hash``, ``size`` and ``mtime``.
* One file per item, named by its SHA-1 hash.

Two properties matter for honesty about what is provable:

1. Category summaries with ``data_type`` 1 or 2 (contacts, calls, SMS,
   calendar, notes, settings) carry a ``count`` but **no** content hash. In this
   package those records are not present as files; the count describes the
   phone, not the backup.
2. ``.backup`` may declare ``xor_obfuscated: true``. Every payload file is then
   transformed, so names and sizes are provable but bytes are not readable
   until the transform is reversed.

This module reports both facts rather than implying the content was parsed.
"""

from __future__ import annotations

import json
import re
import sqlite3
import stat
from pathlib import Path

MAX_HEADER_BYTES = 64 * 1024
MAX_INDEX_ENTRIES = 200_000
MAX_LEVELDB_SECONDS = 30

# Categories that hold files addressed by content hash.
FILE_CATEGORIES = {
    "album": "相册",
    "document": "文档",
    "music": "音乐",
    "video": "视频",
    "record": "录音",
    "zip_file": "压缩包",
}
# Categories that hold structured records and are NOT stored as hash files.
RECORD_CATEGORIES = {
    "contact": "联系人",
    "call": "通话记录",
    "sms": "信息",
    "calender": "日程",
    "notes": "便签",
    "settings": "系统设置",
}
# Application entries use a different key shape: app_<package>.apk / app_<package>.data
APP_KEY = re.compile(r"^app_(?P<package>[A-Za-z0-9._]+)\.(?P<kind>apk|data)$")
ITEM_KEY = re.compile(r"^(?P<category>[a-z_]+)_(?P<index>\d{7})_(?P<hash>[0-9a-f]{40})$")


def _read_header(root: Path) -> dict:
    header = root / ".backup"
    try:
        if not header.is_file() or header.stat().st_size > MAX_HEADER_BYTES:
            return {}
        with header.open("r", encoding="utf-8-sig") as source:
            value = json.load(source)
    except (OSError, ValueError, UnicodeError):
        return {}
    return value if isinstance(value, dict) else {}


def locate_backup_root(path: Path) -> Path | None:
    """Find the directory holding ``.backup`` and ``db/``.

    Accepts the backup directory itself or a wrapper one or two levels above,
    which is the shape produced by extracting the vendor's ZIP.
    """
    def is_backup(candidate: Path) -> bool:
        try:
            return (candidate / ".backup").is_file() and (candidate / "db").is_dir()
        except OSError:
            return False

    if is_backup(path):
        return path

    frontier = [path]
    for _ in range(2):
        next_frontier: list[Path] = []
        found: list[Path] = []
        for parent in frontier:
            try:
                children = [c for c in parent.iterdir() if c.is_dir() and not c.is_symlink()]
            except OSError:
                continue
            for child in children:
                if is_backup(child):
                    found.append(child)
                else:
                    next_frontier.append(child)
        if found:
            found.sort(key=lambda item: (len(item.parts), str(item)))
            return found[0]
        frontier = next_frontier
        if not frontier:
            break
    return None


def _open_leveldb(directory: Path):
    """Open a LevelDB copy so the evidence directory is never written.

    plyvel takes a directory, and LevelDB may write a LOCK file even when the
    caller only reads. Copying the small index first keeps the evidence
    byte-identical.
    """
    import shutil
    import tempfile

    import plyvel

    temp = Path(tempfile.mkdtemp(prefix="tracelens-vivo-db-"))
    target = temp / "db"
    shutil.copytree(directory, target)
    db = plyvel.DB(str(target), create_if_missing=False)
    return db, temp


def _parse_index(root: Path) -> dict:
    """Read the LevelDB index into a normalised summary."""
    import shutil

    db = None
    temp = None
    try:
        db, temp = _open_leveldb(root / "db")
    except Exception as error:  # plyvel raises its own exception types
        return {"available": False, "reason": f"leveldb_open_failed: {error}"}

    summary = {
        "available": True,
        "categories": [],
        "items": [],
        "applications": [],
        "device_properties": {},
        "backup_version": None,
        "created_ms": None,
        "finished_ms": None,
        "encryption_info": [],
        "hidden_apps": [],
        "payload_hint": {},
    }
    try:
        count = 0
        for key, value in db:
            count += 1
            if count > MAX_INDEX_ENTRIES:
                summary["truncated"] = True
                break
            try:
                name = key.decode("utf-8")
            except UnicodeDecodeError:
                continue

            if ITEM_KEY.match(name):
                item = _item_entry(name, value)
                if item:
                    summary["items"].append(item)
                continue
            if APP_KEY.match(name):
                application = _app_entry(name, value)
                if application:
                    summary["applications"].append(application)
                continue

            # Category summaries and singletons.
            try:
                payload = json.loads(value)
            except (ValueError, UnicodeDecodeError):
                payload = None
            if name == "phone" and isinstance(payload, dict):
                summary["device_properties"] = payload.get("PhoneProperties") or {}
            elif name == "version":
                summary["backup_version"] = payload if isinstance(payload, str) else None
            elif name == "create_time":
                summary["created_ms"] = _as_int(payload)
            elif name == "end_time":
                summary["finished_ms"] = _as_int(payload)
            elif name == "encrypt_data_info" and isinstance(payload, list):
                summary["encryption_info"] = payload
            elif name == "hidden_apps_info" and isinstance(payload, list):
                summary["hidden_apps"] = payload
            elif name == "xor_obfuscated":
                summary["payload_hint"]["xor_obfuscated"] = payload is True
            elif name == "note_use_base64":
                summary["payload_hint"]["note_use_base64"] = payload is True
            elif name in RECORD_CATEGORIES and isinstance(payload, dict):
                summary["categories"].append({
                    "key": name,
                    "label": payload.get("name") or RECORD_CATEGORIES[name],
                    "data_type": payload.get("data_type"),
                    "count": _as_int(payload.get("count")),
                    "size": _as_int(payload.get("size")),
                    "stored_as_files": False,
                })
            elif name in FILE_CATEGORIES and isinstance(payload, dict):
                summary["categories"].append({
                    "key": name,
                    "label": payload.get("name") or FILE_CATEGORIES[name],
                    "data_type": payload.get("data_type"),
                    "count": _as_int(payload.get("count")),
                    "size": _as_int(payload.get("size")),
                    "stored_as_files": True,
                    "index_hash": payload.get("hash"),
                    "inner_storage_path": payload.get("innerstoragepath"),
                })
            elif name.startswith("settings_") and isinstance(payload, dict):
                # Per-app settings blobs (settings_<pkg>_<id>): each names a
                # hash file holding that app's exported settings.
                if payload.get("hash"):
                    summary.setdefault("extra_items", []).append({
                        "category": "settings_file",
                        "hash": payload["hash"],
                        "original_path": payload.get("filename") or name,
                        "size": _as_int(payload.get("size")),
                        "mtime_ms": _as_int(payload.get("mtime")),
                    })
            elif name == "app" and isinstance(payload, dict):
                summary["categories"].append({
                    "key": "app",
                    "label": payload.get("name") or "应用",
                    "data_type": payload.get("data_type"),
                    "count": _as_int(payload.get("count")),
                    "size": _as_int(payload.get("size")),
                    "stored_as_files": True,
                })
            elif name == "weixin" and isinstance(payload, dict):
                summary["categories"].append({
                    "key": "weixin",
                    "label": payload.get("name") or "微信",
                    "data_type": payload.get("data_type"),
                    "count": _as_int(payload.get("count")),
                    "size": _as_int(payload.get("size")),
                    "stored_as_files": True,
                })
    finally:
        try:
            if db is not None:
                db.close()
        finally:
            if temp is not None:
                shutil.rmtree(temp, ignore_errors=True)

    summary["categories"].sort(key=lambda row: (row.get("key") or ""))
    # Index every hash-bearing entry, not just the file categories: settings_*
    # and app_* entries also name a payload file.
    summary["hashed_entries"] = len({item["hash"] for item in summary["items"]}
                                   | {app["hash"] for app in summary["applications"] if app.get("hash")}
                                   | set(summary.get("extra_hashes", [])))
    return summary


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _item_entry(name: str, value: bytes) -> dict | None:
    match = ITEM_KEY.match(name)
    if not match:
        return None
    try:
        payload = json.loads(value)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    category = match.group("category")
    if category not in FILE_CATEGORIES:
        return None
    return {
        "category": category,
        "index": int(match.group("index")),
        "hash": match.group("hash"),
        "original_path": payload.get("filename") or "",
        "size": _as_int(payload.get("size")),
        "mtime_ms": _as_int(payload.get("mtime")),
        "created": payload.get("created") or "",
        "version": payload.get("version"),
    }


def _app_entry(name: str, value: bytes) -> dict | None:
    match = APP_KEY.match(name)
    if not match:
        return None
    try:
        payload = json.loads(value)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return {
        "package": payload.get("pkg") or match.group("package"),
        "kind": match.group("kind"),
        # The key here is app_<package>.<apk|data>; the content hash lives in
        # the JSON value, not in the key.
        "hash": payload.get("hash") or "",
        "file_name": payload.get("filename") or "",
        "size": _as_int(payload.get("size")),
        "app_name": payload.get("appName") or "",
        "version_name": payload.get("version_name") or "",
        "version_code": _as_int(payload.get("version_code")),
        "with_data": bool(payload.get("with_data")),
    }


def inspect(path: Path) -> dict:
    """Identify a vivo backup and summarise what it actually contains."""
    root = locate_backup_root(path)
    if root is None:
        return {"kind": "unknown_directory", "ready": False,
                "reason": "no_vivo_backup_header_and_index"}

    header = _read_header(root)
    if not header:
        return {"kind": "vivo_backup_unsupported", "ready": False,
                "backup_root": str(root), "reason": "backup_header_unreadable"}

    encrypted = bool(header.get("encrypted"))
    index = _parse_index(root)

    payload_files = 0
    present_bytes = 0
    missing = 0
    if index.get("available"):
        for item in index.get("items", []):
            shard = root / item["hash"]
            if shard.is_file():
                payload_files += 1
                present_bytes += shard.stat().st_size
            else:
                missing += 1

    obfuscated = bool(index.get("payload_hint", {}).get("xor_obfuscated"))
    categories = index.get("categories", [])
    record_only = [row for row in categories if not row.get("stored_as_files")]
    file_backed = [row for row in categories if row.get("stored_as_files")]

    # Per-category item counts come from the index, not from the phone's own
    # summary, so a reader can see how much of each category is actually here.
    item_counts: dict[str, int] = {}
    for item in index.get("items", []):
        item_counts[item["category"]] = item_counts.get(item["category"], 0) + 1

    warnings: list[str] = []
    if obfuscated:
        warnings.append("payload_xor_obfuscated")
    if missing:
        warnings.append(f"payload_files_missing:{missing}")
    if not index.get("available"):
        warnings.append("index_unreadable")

    # `ready` means the index was read and at least one payload file exists.
    # It does NOT mean the payload bytes are readable, which is why
    # payload_readable is reported separately.
    ready = bool(index.get("available")) and payload_files > 0

    return {
        "kind": "vivo_backup_encrypted" if encrypted else "vivo_backup",
        "ready": ready and not encrypted,
        "backup_root": str(root),
        "encryption_status": "locked" if encrypted else "none",
        "reason": None if ready else (
            "encrypted_backup" if encrypted
            else index.get("reason") or "no_payload_file_present"),
        "model": header.get("model"),
        "backup_package_version": header.get("backupPackageVer"),
        "backup_time_ms": _as_int(header.get("createTime")),
        "backup_success": bool(header.get("success")),
        "index_version": index.get("backup_version"),
        "device_properties": _device_properties(index.get("device_properties") or {}),
        "index_available": bool(index.get("available")),
        "category_count": len(categories),
        "categories": categories,
        "record_categories": record_only,
        "file_categories": file_backed,
        "payload": {
            "obfuscated": obfuscated,
            "xor_obfuscated": obfuscated,
            "readable": not obfuscated,
            "files_indexed": len(index.get("items", [])) + len(index.get("extra_items", [])),
            "files_present": payload_files,
            "files_missing": missing,
            "bytes_present": present_bytes,
        },
        "applications": index.get("applications", []),
        "application_count": len({a["package"] for a in index.get("applications", [])}),
        "item_total": len(index.get("items", [])),
        "item_counts": item_counts,
        "hashed_entries": index.get("hashed_entries", 0),
        "warnings": warnings,
        "index_sha256": _index_fingerprint(root),
    }


def _device_properties(raw: dict) -> dict:
    """Keep the handful of device fields worth showing; drop icon blobs."""
    keep = ("androidVersion", "sdkVersion", "deviceModel", "deviceName", "buildVersion")
    result = {}
    for key in keep:
        if key in raw and not isinstance(raw[key], (dict, list)):
            result[key] = raw[key]
    return result


def _index_fingerprint(root: Path) -> str | None:
    """SHA-256 over the LevelDB files, so a later run can prove they match."""
    import hashlib

    digest = hashlib.sha256()
    try:
        files = sorted(p for p in (root / "db").iterdir() if p.is_file())
    except OSError:
        return None
    try:
        for path in files:
            digest.update(path.name.encode("utf-8"))
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()
