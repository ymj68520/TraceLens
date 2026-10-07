# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicit bounded materialization for the first integration milestone.

Not a TB-sized default. Only COMPLETE packages contain logical.img; failures
retain clearly named partial output and a safe failure manifest for inspection.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import uuid

from .core import RaidError, RaidSession, MAX_REQUEST, digest_json


def write_json(path: Path, value):
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("x", encoding="utf-8") as output:
        json.dump(value, output, sort_keys=True, ensure_ascii=True, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def export_array(session: RaidSession, output_root: Path, *, max_bytes: int,
                 timeout: float = 1800, cancelled=lambda: False) -> dict:
    root = Path(output_root).resolve(strict=True)
    # Do not place generated data anywhere in the selected evidence tree.
    if root.is_relative_to(session.inbox) or session.inbox.is_relative_to(root):
        raise RaidError("OUTPUT_MUST_BE_EVIDENCE_DISJOINT")
    if max_bytes <= 0 or session.size > max_bytes:
        raise RaidError("EXPORT_SIZE_LIMIT_USE_VIRTUAL_READER")
    if timeout <= 0:
        raise RaidError("INVALID_EXPORT_TIMEOUT")
    if shutil.disk_usage(root).free < session.size + 16 * 1024**2:
        raise RaidError("INSUFFICIENT_OUTPUT_SPACE")
    run_id = uuid.uuid4().hex
    target = root / run_id
    target.mkdir(mode=0o700)
    partial = target / "logical.img.partial"
    started = time.monotonic()
    timing = {}
    manifest = {"schema_version": 1, "status": "FAILED", "run_id": run_id,
                "source_type": "raid_logical_view", "created_at": datetime.now(timezone.utc).isoformat()}
    try:
        hashes = session.source_hashes(cancelled=cancelled, deadline=started + timeout)
        timing["source_hash_seconds"] = time.monotonic() - started
        manifest.update(session.manifest(hashes))
        hashed = hashlib.sha256()
        export_start = time.monotonic()
        with partial.open("xb") as output:
            offset = 0
            while offset < session.size:
                if cancelled():
                    raise RaidError("EXPORT_CANCELLED")
                if time.monotonic() - started >= timeout:
                    raise RaidError("EXPORT_TIMEOUT")
                data = session.read_at(offset, min(MAX_REQUEST, session.size - offset))
                output.write(data)
                hashed.update(data)
                offset += len(data)
            output.flush()
            os.fsync(output.fileno())
        timing["logical_read_validate_export_seconds"] = time.monotonic() - export_start
        recheck_start = time.monotonic()
        if cancelled():
            raise RaidError("EXPORT_CANCELLED")
        session.source_hashes(recheck=True, cancelled=cancelled, deadline=started + timeout)
        timing["source_rehash_seconds"] = time.monotonic() - recheck_start
        if time.monotonic() - started >= timeout:
            raise RaidError("EXPORT_TIMEOUT")
        derived = {"path": "logical.img", "sha256": hashed.hexdigest(), "bytes": session.size,
                   "kind": "DERIVED_RECONSTRUCTED_LOGICAL_IMAGE", "includes_member_metadata": False}
        manifest.update(status="COMPLETE", derived_image=derived, timings=timing,
                        validation={**manifest["validation"], "content": "FULL_LOGICAL_READ",
                                    "source_rehash": "PASS"},
                        manifest_hash_scope="all fields except manifest_sha256")
        final = session.manifest(hashes)
        if "parity" in final["validation"]:
            manifest["validation"]["parity"] = final["validation"]["parity"]
        if getattr(session, "parity_mismatch_count", 0):
            manifest["status"] = "PARTIAL"
            manifest["validation"]["parity"] = final["validation"]["parity"]
            manifest["warnings"] = final["warnings"]
            manifest["validation"]["content"] = "FULL_READ_PARITY_MISMATCH"
        manifest["manifest_sha256"] = digest_json(manifest)
        # A completed manifest is the commit marker. Without it output is NOT
        # admitted as a deliverable, including after a process interruption.
        os.rename(partial, target / "logical.img")
        write_json(target / "raid_manifest.json", manifest)
        directory = os.open(target, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return {**manifest, "package_directory": str(target)}
    except BaseException as exc:
        # Do not publish a complete-looking image when commit-marker write fails.
        image = target / "logical.img"
        if image.exists() and not (target / "raid_manifest.json").exists():
            image.rename(partial)
        safe_code = str(exc) if isinstance(exc, RaidError) else "EXPORT_IO_OR_PROCESS_FAILURE"
        failure = {"schema_version": 1, "status": "FAILED", "run_id": run_id,
                   "source_type": "raid_logical_view", "code": safe_code,
                   "partial_output": partial.exists(), "timings": timing}
        try:
            write_json(target / "failure.json", failure)
        except OSError:
            pass
        raise


def verify_package(root: Path, *, allow_partial=False) -> dict:
    """Offline: validate manifest, immutable image bytes and member hash scope."""
    root = Path(root).resolve(strict=True)
    if (root / "raid_manifest.json").is_symlink() or (root / "logical.img").is_symlink():
        raise RaidError("PACKAGE_SYMLINK_FORBIDDEN")
    manifest = json.loads((root / "raid_manifest.json").read_text())
    if manifest.get("status") != "COMPLETE" and not (allow_partial and manifest.get("status") == "PARTIAL"):
        raise RaidError("PACKAGE_NOT_COMPLETE")
    supplied = manifest.pop("manifest_sha256")
    if digest_json(manifest) != supplied:
        raise RaidError("PACKAGE_MANIFEST_CHANGED")
    layout = manifest["layout"]
    if digest_json(layout) != manifest["layout_sha256"]:
        raise RaidError("PACKAGE_LAYOUT_CHANGED")
    expected = manifest["derived_image"]
    if expected["path"] != "logical.img":
        raise RaidError("INVALID_PACKAGE_IMAGE_PATH")
    with (root / "logical.img").open("rb") as image:
        if os.fstat(image.fileno()).st_size != expected["bytes"] or hash_handle_for_package(image) != expected["sha256"]:
            raise RaidError("PACKAGE_IMAGE_CHANGED")
    return {"status": "PASS", "business_status": manifest["status"], "scope": "DELIVERED_PACKAGE_ONLY",
            "source_recheck": "NOT_PERFORMED_OFFLINE", "logical_sha256": expected["sha256"],
            "bytes": expected["bytes"], "warnings": manifest["warnings"]}


def hash_handle_for_package(handle):
    hashed = hashlib.sha256()
    for chunk in iter(lambda: handle.read(MAX_REQUEST), b""):
        hashed.update(chunk)
    return hashed.hexdigest()
