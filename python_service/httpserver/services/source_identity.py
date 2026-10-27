"""Versioned file identity shared by readers, analysis and investigation snapshots."""
from __future__ import annotations
import hashlib
import json
import re
import sqlite3
from urllib.parse import quote, unquote
from ..path_utils import normalize_evidence_path

ID = re.compile(r"^[0-9a-f]{64}$")
REF = re.compile(r"^source:v1:([0-9a-f]{64}):(.*)$", re.S)
KEY = re.compile(r"^file:v2:([0-9a-f]{64}):(.*)$", re.S)


class SourceIdentityError(ValueError):
    def __init__(self, code, message="来源不存在、不唯一或与冻结记录不一致", *, candidates=()):
        super().__init__(code)
        self.code, self.message, self.candidates = code, message, tuple(candidates)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def locator_hash(locator):
    return hashlib.sha256(canonical(locator).encode("utf-8")).hexdigest()


def decode_reference(value):
    value = value or ""
    match = REF.fullmatch(value)
    if match:
        return normalize_evidence_path(match[2]), match[1]
    match = KEY.fullmatch(value)
    if match:
        if re.search(r"%(?![0-9a-fA-F]{2})", match[2]):
            raise SourceIdentityError("SOURCE_KEY_INVALID")
        return normalize_evidence_path(unquote(match[2], errors="strict")), match[1]
    return normalize_evidence_path(value), None


def analysis_reference(path, source_id=None):
    return f"source:v1:{source_id}:{path}" if source_id else path


def evidence_key(path, source_id=None):
    return f"file:v2:{source_id}:{quote(path, safe='')}" if source_id else f"file:{path}"


def has_column(conn, table, name):
    if table not in {"files", "file_analyses"}:
        raise ValueError("unsupported schema probe")
    return any(row[1] == name for row in conn.execute(f"PRAGMA table_info({table})"))


def lookup_locator(conn, source_id):
    if not isinstance(source_id, str) or not ID.fullmatch(source_id):
        raise SourceIdentityError("SOURCE_ID_INVALID")
    try:
        row = conn.execute("SELECT locator_json FROM source_objects WHERE source_id=?", (source_id,)).fetchone()
        meta = conn.execute("SELECT value FROM source_index_meta WHERE key='revision'").fetchone()
    except sqlite3.OperationalError as exc:
        raise SourceIdentityError("SOURCE_INDEX_UNAVAILABLE") from exc
    if not row or not meta:
        raise SourceIdentityError("SOURCE_NOT_FOUND")
    locator = json.loads(row[0])
    if locator_hash(locator) != source_id or locator.get("version") != 1 or locator.get("source_revision") != meta[0]:
        raise SourceIdentityError("SOURCE_LOCATOR_HASH_MISMATCH")
    return locator


def file_row(conn, path, source_id=None):
    """Exact task membership. Path-only requests must resolve exactly one row."""
    path, embedded_id = decode_reference(path)
    if embedded_id and source_id and embedded_id != source_id:
        raise SourceIdentityError("SOURCE_PATH_ID_MISMATCH")
    source_id = source_id or embedded_id
    if source_id:
        locator = lookup_locator(conn, source_id)
        if path and path != locator["logical_path"]:
            raise SourceIdentityError("SOURCE_PATH_ID_MISMATCH")
        path = locator["logical_path"]
        if not has_column(conn, "files", "source_id"):
            raise SourceIdentityError("SOURCE_INDEX_UNAVAILABLE")
        cursor = conn.execute("SELECT rowid AS source_row_id,* FROM files WHERE path=? AND source_id=?", (path, source_id))
    else:
        locator = None
        cursor = conn.execute("SELECT rowid AS source_row_id,* FROM files WHERE path=?", (path,))
    columns = [d[0] for d in cursor.description]
    rows = [dict(zip(columns, r)) for r in cursor.fetchmany(2)]
    if not rows:
        raise SourceIdentityError("SOURCE_NOT_FOUND")
    if len(rows) != 1:
        raise SourceIdentityError("SOURCE_PATH_AMBIGUOUS", "同一路径有多个来源记录，请选择分区、记录及删除状态", candidates=[{k:r.get(k) for k in ("source_id","path","partition_num","inode","is_deleted","size")} for r in rows])
    row = rows[0]
    if source_id:
        expected = {"path": locator["logical_path"], "size": locator["size"], "mtime": locator["mtime"], "ctime": locator["ctime"], "is_deleted": locator["is_deleted"]}
        if locator["source_kind"] == "physical":
            expected.update(inode=locator["inode"], partition_num=locator["partition_num"])
        else:
            expected["inode"] = locator["entry_id"]
        if any(row.get(k) != value for k,value in expected.items()):
            raise SourceIdentityError("SOURCE_RECORD_CHANGED")
    return row, locator
