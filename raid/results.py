# SPDX-License-Identifier: AGPL-3.0-or-later
"""Machine-extracted file results with explicit original-member read-back.

Independent result DB, no fake Android records/events or migration of old keys.
Locations are SDK metadata locators plus READ_TRACE, not invented byte extents.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

from .core import RaidError, digest_json
from .raw import RawRaidSession
from .filesystems import boot_spec, open_fs
from .export import write_json, verify_package


def session_for_package(inbox, package, *, allow_partial=False):
    verify_package(package, allow_partial=allow_partial)
    manifest = json.loads((package / "raid_manifest.json").read_text())
    if str(Path(inbox).resolve(strict=True)) != manifest["source_root"] or manifest["layout"]["metadata"] is not None:
        raise RaidError("PACKAGE_SOURCE_ROOT_OR_TYPE_MISMATCH")
    entries = sorted(manifest["layout"]["members"], key=lambda m: m["input_index"])
    members = [{"files": m["files"]} for m in entries]
    layout = manifest["layout"]
    order = [m["input_index"] for m in sorted(entries, key=lambda m: m["role"])]
    plan = {"level": layout["level"], "layout": layout["layout"], "chunk_size": layout["chunk_size"],
            "order": order, "data_offset": 0}
    session = RawRaidSession(inbox, members, plan, inference=manifest.get("inference"),
                             parity_mode="observe" if allow_partial else "strict")
    try:
        if session.source_hashes() != manifest["source_sha256"]:
            raise RaidError("ORIGINAL_MEMBERS_CHANGED")
    except Exception:
        session.close()
        raise
    return session, manifest


def iter_files(fs, kind, *, max_files=2000):
    root = fs.mft.get(5) if kind == "ntfs" else fs.root
    queue = [(root, "", 0)]
    seen = set()
    count = 0
    while queue:
        parent, prefix, depth = queue.pop()
        if depth > 32:
            raise RaidError("FS_DIRECTORY_DEPTH_LIMIT")
        entries = parent.iterdir(ignore_dos=True) if kind == "ntfs" else parent.iterdir()
        for entry in entries:
            node = entry.dereference() if kind == "ntfs" else entry
            name = entry.attribute.file_name if kind == "ntfs" else node.name
            if name in (".", ".."): continue
            if "/" in name or "\\" in name or "\0" in name:
                raise RaidError("UNSAFE_FILESYSTEM_NAME")
            path = prefix + "/" + name
            is_dir = node.is_dir() if kind == "ntfs" else node.is_directory()
            identity = node.segment if kind == "ntfs" else node.cluster
            if is_dir:
                if identity in seen: continue
                seen.add(identity)
                queue.append((node, path, depth + 1))
            else:
                size = (node.size() if node.has_stream() else 0) if kind == "ntfs" else node.size
                count += 1
                if count > max_files: return  # caller records a conservative limit warning
                locator = {"kind": "NTFS_MFT_RECORD", "segment": node.segment} if kind == "ntfs" else \
                    {"kind": "FAT_DIRENT", "cluster": node.cluster, "path": path}
                yield path, size, locator, node


def hash_stream(stream, size, *, max_file_bytes):
    if size < 0 or size > max_file_bytes: raise RaidError("FS_FILE_SIZE_LIMIT")
    digest = hashlib.sha256()
    left = size
    while left:
        chunk = stream.read(min(left, 65536))
        if not chunk: raise RaidError("FS_FILE_SHORT_READ")
        digest.update(chunk)
        left -= len(chunk)
    return digest.hexdigest()


def create_results(inbox, package: Path, *, volume_offset: int, allow_partial=False,
                   max_files=2000, max_file_bytes=512 * 1024**2):
    session, manifest = session_for_package(inbox, package, allow_partial=allow_partial)
    output = package / "file-results"
    output.mkdir(mode=0o700)
    count = 0
    failure_count = 0
    rows = []
    with session:
        session._probe_defer_guards = True
        spec = boot_spec(session.read_at(volume_offset, 512))
        if spec is None or spec["base"] != volume_offset:
            raise RaidError("SELECTED_VOLUME_BOOT_MISMATCH")
        fs, trace = open_fs(session, spec)
        db = sqlite3.connect(output / "results.db")
        db.execute("CREATE TABLE files (record_id TEXT PRIMARY KEY, path TEXT, size INTEGER, sha256 TEXT, "
                   "source_type TEXT, verification_state TEXT, locator_json TEXT, read_trace_json TEXT, status TEXT)")
        try:
            with (output / "files.jsonl").open("x", encoding="utf-8") as exported:
                for path, size, locator, node in iter_files(fs, spec["kind"], max_files=max_files):
                    identifier = digest_json({"volume_offset": volume_offset, "path": path, "locator": locator})[:32]
                    trace.trace.clear()
                    try:
                        with node.open() as stream:
                            sha = hash_stream(stream, size, max_file_bytes=max_file_bytes)
                        status = "READABLE"
                    except Exception:
                        sha, status = None, "UNREADABLE_OR_LIMITED"
                        failure_count += 1
                    location = {"volume_offset": volume_offset, "filesystem": spec["kind"], **locator}
                    item = {"record_id": identifier, "path": path, "size": size, "sha256": sha,
                            "source_type": "raid_reassembled_file", "verification_state": "MACHINE_EXTRACTED_UNVERIFIED",
                            "locator": location, "read_trace": list(trace.trace), "trace_scope": "READ_TRACE_NOT_EXACT_FILE_EXTENTS",
                            "status": status}
                    db.execute("INSERT INTO files VALUES (?,?,?,?,?,?,?,?,?)",
                        (identifier, path, size, sha, item["source_type"], item["verification_state"],
                         json.dumps(location), json.dumps(trace.trace), status))
                    exported.write(json.dumps(item, ensure_ascii=True) + "\n")
                    rows.append(item)
                    count += 1
            session._probe_defer_guards = False
            session.source_hashes(recheck=True)
            db.commit()
        finally:
            db.close()
        limited = count >= max_files
        result = {"schema_version": 1, "status": "PARTIAL" if failure_count or limited or manifest["status"] == "PARTIAL" else "COMPLETE",
                  "file_count": count, "unreadable_files": failure_count, "volume_offset": volume_offset,
                  "enumeration_limit_reached": limited,
                  "source_manifest_sha256": manifest["manifest_sha256"],
                  "verification_state": "MACHINE_EXTRACTED_UNVERIFIED", "source_type": "raid_reassembled_file",
                  "results_db_sha256": _file_hash(output / "results.db"),
                  "warnings": manifest["warnings"] + ["CONTENT_REFERENCE_VALIDATION_REQUIRED"] +
                    (["FILE_ENUMERATION_LIMIT_REACHED"] if limited else [])}
        write_json(output / "result_manifest.json", result)
        return result


def read_back(inbox, package: Path, record_id, *, allow_partial=False):
    session, manifest = session_for_package(inbox, package, allow_partial=allow_partial)
    dbpath = package / "file-results" / "results.db"
    try:
        result_manifest = json.loads((dbpath.parent / "result_manifest.json").read_text())
        if result_manifest["source_manifest_sha256"] != manifest["manifest_sha256"] or \
                _file_hash(dbpath) != result_manifest["results_db_sha256"] or dbpath.is_symlink():
            raise RaidError("RESULT_DATABASE_OR_SOURCE_BINDING_CHANGED")
    except Exception:
        session.close()
        raise
    with sqlite3.connect(f"file:{dbpath}?mode=ro", uri=True) as db:
        row = db.execute("SELECT path,size,sha256,locator_json,status FROM files WHERE record_id=?", (record_id,)).fetchone()
    if not row or row[4] != "READABLE":
        session.close()
        raise RaidError("RESULT_RECORD_UNAVAILABLE")
    locator = json.loads(row[3])
    with session:
        session._probe_defer_guards = True
        spec = boot_spec(session.read_at(locator["volume_offset"], 512))
        fs, trace = open_fs(session, spec)
        node = fs.mft.get(locator["segment"]) if locator["kind"] == "NTFS_MFT_RECORD" else fs.get(row[0])
        # Preserve metadata reads too: a resident file's body lives in its MFT
        # record, possibly already read while opening the filesystem.
        with node.open() as stream:
            observed = hash_stream(stream, row[1], max_file_bytes=512 * 1024**2)
        session._probe_defer_guards = False
        session.source_hashes(recheck=True)
        if observed != row[2]: raise RaidError("FILE_CONTENT_READBACK_MISMATCH")
        mappings = []
        for read in trace.trace[:128]:
            mappings.extend(session.map_range(read["logical_offset"], read["length"], limit=4096))
        return {"status": "MATCH", "record_id": record_id, "sha256": observed, "locator": locator,
                "verification_state": "MACHINE_EXTRACTED_UNVERIFIED", "member_reads": mappings,
                "mapping_scope": "READ_TRACE_INCLUDES_METADATA_NOT_EXACT_FILE_EXTENTS",
                "location_granularity": locator["kind"], "package_business_status": manifest["status"]}


def _file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for data in iter(lambda: handle.read(1024**2), b""): digest.update(data)
    return digest.hexdigest()
