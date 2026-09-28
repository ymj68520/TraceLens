"""Read-only Android userdata image inspection. No FS mutation or extraction."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ..config import get_project_root
from .android_encryption_inspector import AndroidEncryptionInspector


def inspect(path: Path) -> dict:
    bridge = get_project_root() / "scripts/android_image_reader_bridge.py"
    try:
        completed = subprocess.run(
            [sys.executable, str(bridge), "inspect", str(path)],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"inspected": False, "ready": False, "reason": "IMAGE_INSPECTION_TIMEOUT"}
    if completed.returncode or len(completed.stdout) > 16 * 1024 * 1024:
        try:
            detail = json.loads(completed.stderr.decode("utf-8").splitlines()[-1])
            reason = detail.get("code", "IMAGE_READER_FAILED")
        except (UnicodeError, ValueError, IndexError, TypeError):
            reason = "IMAGE_READER_FAILED"
        return {"inspected": False, "ready": False, "reason": reason}
    try:
        parsed = json.loads(completed.stdout)
        if parsed["status"] != "OK" or not isinstance(parsed["volumes"], list):
            raise ValueError("invalid image reader result")
        volumes = parsed["volumes"]
    except (ValueError, KeyError, TypeError):
        return {"inspected": False, "ready": False, "reason": "INVALID_IMAGE_READER_RESULT"}
    candidates = []
    metadata_fstab = ("metadata_encryption=" if any(
        "metadata_encryption" in (volume.get("fstab_flags") or []) for volume in volumes
    ) else None)
    for volume in volumes:
        if volume.get("kind") not in ("ext4", "f2fs"):
            continue
        markers = volume.get("android_markers") or []
        feature = volume.get("feature_flags") or 0
        fbe = (volume["kind"] == "f2fs" and bool(feature & 1)) or (
            volume["kind"] == "ext4" and bool(feature & 0x10000))
        name = f"{volume.get('label', '')} {volume.get('name', '')}".lower()
        locked_candidate = fbe and "userdata" in name and not markers
        if not markers and not locked_candidate:
            continue
        encrypted = int(volume.get("encrypted_files") or 0)
        readable = int(volume.get("readable_files") or 0)
        assessment = AndroidEncryptionInspector.inspect(volume, metadata_fstab=metadata_fstab)
        if locked_candidate:
            assessment = {**assessment, "state": "LOCKED",
                          "evidence": assessment["evidence"] + ["partition_label_userdata_no_clear_markers"]}
        candidates.append({**volume, "encryption": assessment,
                           "locked": bool(locked_candidate or (encrypted and not readable))})
    selected = max(candidates, key=lambda item: len(item.get("android_markers", [])), default=None)
    segment_count = int(parsed.get("segment_count", 1))
    ready = bool(selected and selected.get("readable") and
                 int(selected.get("readable_files") or 0) > 0 and
                 not selected.get("locked") and
                 not selected.get("missing_past_end") and selected.get("android_markers") and
                 segment_count == 1)
    return {"inspected": True, "ready": ready, "reader": parsed.get("reader"),
            "container": parsed.get("container", "unknown"),
            "segment_count": segment_count,
            "volumes": volumes, "android_candidates": candidates,
            "selected_partition": selected,
            "reason": "ANDROID_USERDATA_CONFIRMED" if ready else
                      "EWF_SEGMENT_SET_HASH_NOT_VERIFIED" if segment_count > 1 else
                      "ANDROID_USERDATA_LOCKED" if selected and selected["locked"] else
                      "NO_READABLE_ANDROID_USERDATA"}
