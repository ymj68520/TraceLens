#!/usr/bin/env python3
"""Validate an explicitly named, external sample manifest; never scan for samples."""

import argparse
import hashlib
import json
import string
from pathlib import Path

REQUIRED = {"sample_id", "source_category", "files", "extraction_tool", "container",
            "filesystem", "readability", "target_artifacts", "expected_records",
            "comparison_source", "validation_status"}


def validate(path: Path, *, full_hash: bool = False) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError("manifest must be an explicit regular file")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or REQUIRED - set(manifest):
        raise ValueError("sample manifest lacks required fields")
    if not isinstance(manifest["files"], list) or not manifest["files"]:
        raise ValueError("sample manifest needs an explicit file list")
    if manifest["validation_status"] != "REAL_SAMPLE_REQUIRED" and not manifest.get("authorization_record"):
        raise ValueError("authorized field sample requires an explicit authorization record")
    expected_kinds = {"sms", "contacts", "apps", "wifi"}
    targets = manifest["target_artifacts"]
    if not isinstance(targets, list) or not targets or any(not isinstance(kind, str) for kind in targets):
        raise ValueError("target_artifacts must list exact artifact kinds")
    unsupported = sorted(set(targets) - expected_kinds)
    declared_other = {item.get("artifact") for item in manifest.get("other_app_requirements", [])
                      if isinstance(item, dict)}
    if any(kind not in declared_other for kind in unsupported):
        raise ValueError("non-core App targets need separate sample-driven requirements")
    results = []

    def inspect(item: dict, *, group: str, index: int) -> None:
        candidate = Path(item.get("local_path", ""))
        if not candidate.is_absolute() or not candidate.is_file() or candidate.is_symlink():
            results.append({"group": group, "index": index, "status": "UNAVAILABLE_OR_UNSAFE"})
            return
        expected = item.get("sha256")
        if not isinstance(expected, str) or len(expected) != 64 or any(ch not in string.hexdigits for ch in expected):
            results.append({"group": group, "index": index, "status": "HASH_NOT_PROVIDED"})
            return
        if not full_hash:
            results.append({"group": group, "index": index, "status": "HASH_NOT_CHECKED"})
            return
        digest = hashlib.sha256()
        with candidate.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        results.append({"group": group, "index": index,
                        "status": "MATCH" if digest.hexdigest() == expected.lower() else "MISMATCH"})

    for index, item in enumerate(manifest["files"]):
        inspect(item, group="files", index=index)
        for segment_index, segment in enumerate(item.get("segments") or []):
            inspect(segment, group=f"files[{index}].segments", index=segment_index)
    for index, attachment in enumerate(manifest.get("attachments") or []):
        inspect(attachment, group="attachments", index=index)
    goal = manifest.get("business_goal") or {}
    locked_goal_unmet = (manifest.get("readability") == "LOCKED" and
                         goal.get("required_messages_readable") is True)
    return {"sample_id": manifest["sample_id"], "validation_status": manifest["validation_status"],
            "files": results, "real_sample_acceptance": "UNMET_LOCKED" if locked_goal_unmet else "NOT_RUN_BY_THIS_TOOL",
            "other_app_targets": unsupported,
            "ready_for_analysis": bool(manifest.get("authorization_record")) and
                not locked_goal_unmet and all(item["status"] == "MATCH" for item in results)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--full-hash", action="store_true", help="read every listed file to check SHA-256")
    args = parser.parse_args()
    result = validate(args.manifest, full_hash=args.full_hash)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    valid_paths = all(item["status"] not in {"UNAVAILABLE_OR_UNSAFE", "MISMATCH"} for item in result["files"])
    accepted_ready = result["validation_status"] == "REAL_SAMPLE_REQUIRED" or result["ready_for_analysis"]
    return 0 if valid_paths and accepted_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
