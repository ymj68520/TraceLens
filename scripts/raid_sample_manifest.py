#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicit authorized RAID sample inventory, not a reconstruction verdict.

Never scan a parent path, mount media, write evidence, execute embedded files,
infer RAID geometry from directory names or contact model/network services.
The generated manifest is private runtime data and must NOT be committed.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from raid.core import RaidError, confined_open, digest_json, fingerprint, hash_handle
from raid.export import write_json
from raid import vendor

MAX_FILES = 2000
MAX_DEPTH = 12


def paths_within(root: Path):
    """Do not follow directory links, including links pointing inside the root."""
    result = []
    skipped = []
    for directory, dirs, names in os.walk(root, followlinks=False):
        base = Path(directory)
        depth = len(base.relative_to(root).parts)
        for name in list(dirs):
            child = base / name
            if child.is_symlink() or depth >= MAX_DEPTH:
                dirs.remove(name)
                skipped.append({"path": child.relative_to(root).as_posix(),
                                "reason": "SYMLINK_OR_DEPTH_LIMIT"})
        for name in sorted(names):
            path = base / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                skipped.append({"path": relative, "reason": "SYMLINK"})
            elif path.is_file():
                result.append(relative)
            else:
                skipped.append({"path": relative, "reason": "NOT_REGULAR_FILE"})
            if len(result) + len(skipped) > MAX_FILES:
                raise RaidError("SAMPLE_INVENTORY_FILE_LIMIT")
    return sorted(result), skipped


def inventory(samples: Path, output_root: Path, *, full_hash: bool, timeout: float = 1800):
    source = samples.resolve(strict=True)
    target_root = output_root.resolve(strict=True)
    if not source.is_dir() or source == Path(source.anchor) or not math.isfinite(timeout) or timeout <= 0:
        raise RaidError("INVALID_EXPLICIT_SAMPLE_ROOT")
    if target_root.is_relative_to(source) or source.is_relative_to(target_root):
        raise RaidError("OUTPUT_MUST_BE_EVIDENCE_DISJOINT")
    destination = target_root / uuid.uuid4().hex
    destination.mkdir(mode=0o700)
    start = time.monotonic()
    md = vendor.volume()
    paths, skipped = paths_within(source)
    records = []
    groups = defaultdict(list)
    identities = {}
    try:
        for relative in paths:
            before = time.monotonic()
            if before - start > timeout:
                raise RaidError("SAMPLE_INVENTORY_TIMEOUT")
            with confined_open(source, relative) as handle:
                identity = fingerprint(handle)
                identities[relative] = identity
                handle.seek(0)
                signature = handle.read(4096)
                item = {"source_file": relative, "bytes": identity[2],
                        "sha256": None, "source_unchanged": None,
                        "source_kind": "OTHER_SAMPLE_MATERIAL"}
                if Path(relative).suffix.lower() in {".img", ".raw", ".dd", ".bin", ".hdd"}:
                    item["source_kind"] = "MEMBER_IMAGE_CANDIDATE"
                    sector, major, _ = md.find_super_block(handle)
                    item["md_metadata"] = {"detected": sector is not None,
                                           "offset": sector * 512 if sector is not None else None,
                                           "major_version": major,
                                           "checksum_verified": False}
                    # A member's boot marker is NOT proof of a reassembled FS.
                    item["boot_marker_candidate"] = ("NTFS" if signature[3:11] == b"NTFS    " else
                        "FAT32" if signature[82:90] == b"FAT32   " else
                        "FAT16" if signature[54:62] == b"FAT16   " else None)
                    item["current_adapter_status"] = (
                        "MD_CHECKSUM_AND_ARRAY_VALIDATION_PENDING" if sector is not None else
                        "NO_MD_METADATA_ADAPTER_REQUIRED")
                    group_path = Path(relative).parent.as_posix()
                    groups[group_path].append(relative)
                elif signature.startswith(b"PK\x03\x04"):
                    item["source_kind"] = "ARCHIVE_NOT_EXTRACTED"
                if full_hash:
                    item["sha256"] = hash_handle(handle, deadline=start + timeout)
                if fingerprint(handle) != identity:
                    raise RaidError("SOURCE_CHANGED_DURING_INVENTORY")
                with confined_open(source, relative) as current:
                    if fingerprint(current) != identity:
                        raise RaidError("SOURCE_REPLACED_DURING_INVENTORY")
                item["source_unchanged"] = True
                item["read_seconds"] = time.monotonic() - before
                records.append(item)
        if paths_within(source)[0] != paths:
            raise RaidError("SAMPLE_FILE_SET_CHANGED")
        # A file hashed early may change while later files are being read.
        # Recheck all selected identities at the end, not only per-file reads.
        for relative, identity in identities.items():
            with confined_open(source, relative) as current:
                if fingerprint(current) != identity:
                    raise RaidError("SOURCE_CHANGED_BEFORE_INVENTORY_COMMIT")
        images = [item for item in records if item["source_kind"] == "MEMBER_IMAGE_CANDIDATE"]
        groups_result = [{"sample_id": hashlib.sha256(name.encode()).hexdigest()[:24],
                          "selection_group": name, "grouping_basis": "DIRECTORY_ONLY_NOT_ARRAY_PROOF",
                          "members": sorted(members), "member_count": len(members),
                          "reassembly_validation": "NOT_RUN"}
                         for name, members in sorted(groups.items())]
        warnings = ["REASSEMBLY_NOT_VALIDATED", "AUTOMATIC_ORDER_NOT_VALIDATED",
                    "DIRECTORY_NAMES_ARE_NOT_ALGORITHM_INPUT",
                    "REFERENCE_LOGICAL_IMAGE_NOT_PROVIDED"]
        if any(not item["md_metadata"]["detected"] for item in images):
            warnings.append("CURRENT_MD_ADAPTER_DOES_NOT_COVER_ALL_SAMPLES")
        if any(item["source_kind"] == "ARCHIVE_NOT_EXTRACTED" for item in records):
            warnings.append("ARCHIVE_MEMBERS_NOT_INCLUDED_OR_DEDUPLICATED")
        if skipped:
            warnings.append("SKIPPED_SOURCE_ENTRIES")
        manifest = {"schema_version": 1, "source_root": str(source),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "status": "INVENTORIED_NOT_ACCEPTED", "hash_scope": "FULL_FILES" if full_hash else "NOT_CALCULATED",
                    "files": records, "groups": groups_result, "skipped": skipped,
                    "summary": {"file_count": len(records), "image_count": len(images),
                                "group_count": len(groups_result), "total_bytes": sum(i["bytes"] for i in records),
                                "md_metadata_candidates": sum(i["md_metadata"]["detected"] for i in images),
                                "source_unchanged": all(i["source_unchanged"] for i in records),
                                "runtime_seconds": time.monotonic() - start},
                    "warnings": warnings,
                    "manifest_hash_scope": "all fields except manifest_sha256"}
        manifest["manifest_sha256"] = digest_json(manifest)
        write_json(destination / "sample_manifest.json", manifest)
        return {"status": manifest["status"], "manifest_path": str(destination / "sample_manifest.json"),
                "summary": manifest["summary"], "warnings": warnings}
    except Exception as exc:
        write_json(destination / "failure.json", {"status": "FAILED", "stage": "SAMPLE_INVENTORY",
                   "code": str(exc) if isinstance(exc, RaidError) else "SOURCE_INVENTORY_FAILED"})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--full-hash", action="store_true")
    parser.add_argument("--timeout", type=float, default=1800)
    args = parser.parse_args()
    print(json.dumps(inventory(args.samples, args.output_directory,
                               full_hash=args.full_hash, timeout=args.timeout), indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "code": str(exc) if isinstance(exc, RaidError) else
                          "SAMPLE_INVENTORY_FAILED"}), file=sys.stderr)
        raise SystemExit(2)
