"""Pinned AOSP liblp inventory and selective lpunpack orchestration."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import shutil
import subprocess
import sys
import time

from ..config import get_project_root
from .android_sparse_image import file_sha256

CORE_COMMIT = "204bd34e58de124ead5a1e65b852608620077b84"
EXTRAS_COMMIT = "ef17b323e8be065ed9fbcd1ea863d72e63488fc0"
TOOL_VERSION = "AOSP android-10.0.0_r36"
TOOL_HASHES = {
    "liblp.so": "15dda55ad2bfd0e0ea867f7e4834017ff70338a01184d3d0cdfdf7f9ece0bf0e",
    "lpmake": "c46c73fcb80871f38134750a9661e87d3940b1b1f1df15c4b3f9d29c22a7d518",
    "lpunpack": "8acbc953127f0da88f995f1be43f15b499eb4410ece0bd3df29e199b41170b48",
    "lp_inventory": "40bf009e33a9f0b800c9134e3bfdbb66665d5c33475ccba51ccc4e6a9e8dbe00",
}
LP_GEOMETRY_MAGIC = b"\x67\x44\x6c\x61"
MAX_INVENTORY_BYTES = 8 * 1024 * 1024


class LpError(ValueError):
    pass


def tool_root() -> Path:
    return get_project_root() / ".deps" / "aosp-android10-r36"


def verify_tools() -> Path:
    root = tool_root()
    for subdir, expected in (("core", CORE_COMMIT), ("extras", EXTRAS_COMMIT)):
        completed = subprocess.run(["/usr/bin/git", "-C", str(root / subdir), "rev-parse", "HEAD"],
                                   capture_output=True, text=True, timeout=10, check=False)
        if completed.returncode or completed.stdout.strip() != expected:
            raise LpError("AOSP_LIBLP_SOURCE_PIN_MISMATCH")
    for name, expected in TOOL_HASHES.items():
        path = root / "bin" / name
        if not path.is_file() or path.is_symlink() or file_sha256(path) != expected:
            raise LpError("AOSP_LIBLP_BINARY_PIN_MISMATCH")
    return root / "bin"


def geometry_candidate(path: Path, *, offset: int = 0) -> bool:
    with Path(path).open("rb") as source:
        source.seek(offset + 4096)
        first = source.read(4)
        source.seek(offset + 8192)
        second = source.read(4)
    return first == LP_GEOMETRY_MAGIC or second == LP_GEOMETRY_MAGIC


def find_super_regions(image: Path) -> list[dict]:
    """Locate LP geometry in a raw/EWF logical block view, not by filename."""
    script_dir = str(get_project_root() / "scripts")
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    from android_image_reader_bridge import _reader  # pinned source SHA checked there
    qp = _reader()
    image = Path(image).resolve(strict=True)
    found = []
    with qp.open_image(str(image)) as handle:
        segment_count = len(getattr(handle, "paths", [image]))
        if segment_count != 1:
            raise LpError("EWF_SEGMENT_SET_HASH_NOT_VERIFIED")
        for volume in qp.volumes(handle):
            base, length = int(volume["base"]), int(volume["size"])
            if base < 0 or length < 12288:
                continue
            handle.seek(base + 4096)
            first = handle.read(4)
            handle.seek(base + 8192)
            second = handle.read(4)
            if first == LP_GEOMETRY_MAGIC or second == LP_GEOMETRY_MAGIC:
                label = volume.get("label", "")
                match = re.search(r"(?:GPT|MBR) part (\d+)\b", label)
                found.append({"offset": base, "size": length,
                              "partition_number": int(match.group(1)) if match else None,
                              "partition_name": volume.get("name", ""),
                              "partition_label": label,
                              "container": "e01" if qp.looks_like_ewf(str(image)) else "raw"})
    return found


def derive_super_region(image: Path, region: dict, output: Path,
                        *, source_sha256: str) -> dict:
    """Copy only the confirmed physical super partition into owned workdir."""
    image, output = Path(image).resolve(strict=True), Path(output)
    if file_sha256(image) != source_sha256:
        raise LpError("EVIDENCE_CHANGED_AFTER_PREFLIGHT")
    parent = output.parent.resolve(strict=True)
    if output.exists() or output.is_symlink() or image == output.resolve(strict=False):
        raise LpError("SUPER_OUTPUT_EXISTS_OR_OVERLAPS_SOURCE")
    size, offset = int(region["size"]), int(region["offset"])
    if size <= 0 or size > 8 * 1024**4 or offset < 0:
        raise LpError("SUPER_REGION_SIZE_UNSUPPORTED")
    reserve = max(256 * 1024 * 1024, size // 20)
    if shutil.disk_usage(parent).free < size + reserve:
        raise LpError("INSUFFICIENT_WORKSPACE")
    script_dir = str(get_project_root() / "scripts")
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    from android_image_reader_bridge import _reader
    qp = _reader()
    started = time.monotonic()
    copied = 0
    try:
        with qp.open_image(str(image)) as source, output.open("xb") as sink:
            source.seek(offset)
            while copied < size:
                chunk = source.read(min(4 * 1024 * 1024, size - copied))
                if not chunk:
                    raise LpError("SUPER_REGION_SHORT_READ")
                sink.write(chunk)
                copied += len(chunk)
            sink.flush()
            os.fsync(sink.fileno())
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return {"disk_image_sha256": source_sha256,
            "partition_number": region.get("partition_number"),
            "partition_name": region.get("partition_name", ""),
            "partition_offset": offset, "partition_length": size,
            "derived_super_path": str(output.resolve()),
            "derived_super_sha256": file_sha256(output),
            "copy_seconds": round(time.monotonic() - started, 3),
            "bytes_written": copied}


def inspect_super(path: Path, slot: int = 0) -> dict:
    if not isinstance(slot, int) or not 0 <= slot <= 31:
        raise LpError("INVALID_METADATA_SLOT")
    path = Path(path).resolve(strict=True)
    if not geometry_candidate(path):
        return {"status": "NOT_ANDROID_SUPER", "ready": False}
    bin_dir = verify_tools()
    started = time.monotonic()
    try:
        completed = subprocess.run([str(bin_dir / "lp_inventory"), str(path), str(slot)],
                                   stdin=subprocess.DEVNULL, capture_output=True,
                                   timeout=120, check=False)
    except subprocess.TimeoutExpired:
        return {"status": "MALFORMED_SUPER", "ready": False, "reason": "LP_PROBE_TIMEOUT"}
    if completed.returncode or len(completed.stdout) > MAX_INVENTORY_BYTES:
        return {"status": "MALFORMED_SUPER", "ready": False,
                "reason": "LP_METADATA_INVALID_OR_EXTENT_OUT_OF_RANGE"}
    try:
        inventory = json.loads(completed.stdout)
        if inventory["status"] != "ANDROID_SUPER" or not isinstance(inventory["partitions"], list):
            raise ValueError("invalid inventory")
    except (ValueError, TypeError, KeyError):
        return {"status": "MALFORMED_SUPER", "ready": False, "reason": "LP_INVENTORY_INVALID"}
    inventory["metadata_parse_seconds"] = round(time.monotonic() - started, 3)
    inventory["selected_partition_count"] = 0
    inventory["extracted_bytes"] = 0
    inventory["extraction_seconds"] = 0
    inventory["userdata"] = {"status": "NOT_PRESENT_IN_SOURCE"}
    inventory["virtual_ab"] = "UNKNOWN_OR_NOT_RECONSTRUCTED"
    if inventory.get("multi_device"):
        inventory["ready"] = False
        inventory["reason"] = "MULTI_DEVICE_SUPER_INPUT_REQUIRED"
    else:
        inventory["ready"] = True
    return inventory


class AndroidSuperImageProbe:
    """Production LP probe: magic candidate, then AOSP liblp verification."""

    @staticmethod
    def find_regions(image: Path) -> list[dict]:
        return find_super_regions(image)

    @staticmethod
    def inspect(path: Path, slot: int = 0) -> dict:
        return inspect_super(path, slot)


def select_partitions(inventory: dict, *, slot: int) -> list[dict]:
    """Select only common system partitions of the explicitly requested slot."""
    if inventory.get("status") != "ANDROID_SUPER" or not inventory.get("ready"):
        raise LpError(inventory.get("reason", "SUPER_NOT_READY"))
    if slot != inventory.get("slot"):
        raise LpError("METADATA_SLOT_MISMATCH")
    allowed = ("system", "system_ext", "product", "vendor", "odm")
    selected = []
    for partition in inventory["partitions"]:
        name = partition["name"]
        stem = name.removesuffix("_a").removesuffix("_b")
        if stem in allowed and int(partition.get("size", 0)) > 0:
            selected.append(partition)
    return selected


def probe_filesystem(path: Path) -> str:
    with Path(path).open("rb") as source:
        source.seek(1024)
        magic = source.read(4)
        source.seek(1080)
        ext_magic = source.read(2)
    if magic == b"\xe2\xe1\xf5\xe0":
        return "EROFS"
    if magic == b"\x10\x20\xf5\xf2" or ext_magic == b"\x53\xef":
        script_dir = str(get_project_root() / "scripts")
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)
        from android_image_reader_bridge import _reader
        qp = _reader()
        try:
            with qp.open_image(str(path)) as image:
                for volume in qp.volumes(image):
                    if volume["base"] == 0 and volume.get("walker") and \
                            volume["kind"] in ("f2fs", "ext4"):
                        return volume["kind"].upper()
        except Exception:
            return "UNKNOWN"
    return "UNKNOWN"


def extract_selected(source: Path, inventory: dict, output_dir: Path,
                     *, slot: int, source_sha256: str, source_image_sha256: str,
                     metadata_slot: int | None = None) -> tuple[list[dict], dict]:
    source = Path(source).resolve(strict=True)
    output_dir = Path(output_dir).resolve(strict=True)
    if source == output_dir or not output_dir.is_dir() or not inventory.get("ready"):
        raise LpError("SUPER_EXTRACTION_NOT_READY")
    if file_sha256(source) != source_sha256:
        raise LpError("EVIDENCE_CHANGED_AFTER_PREFLIGHT")
    bin_dir = verify_tools()
    selected = select_partitions(inventory, slot=slot)
    required = sum(int(item["size"]) for item in selected)
    reserve = max(256 * 1024 * 1024, required // 20)
    if shutil.disk_usage(output_dir).free < required + reserve:
        raise LpError("INSUFFICIENT_WORKSPACE")
    results = []
    started = time.monotonic()
    for partition in selected:
        name = partition["name"]
        if not name or len(name) > 36 or not all(c.isascii() and (c.isalnum() or c == "_") for c in name):
            raise LpError("UNSAFE_LP_PARTITION_NAME")
        target = output_dir / f"{name}.img"
        if target.exists() or target.is_symlink():
            raise LpError("LP_OUTPUT_EXISTS")
        try:
            completed = subprocess.run([str(bin_dir / "lpunpack"), f"--slot={slot}",
                                        f"--partition={name}", str(source), str(output_dir)],
                                       stdin=subprocess.DEVNULL, capture_output=True,
                                       timeout=3600, check=False)
        except subprocess.TimeoutExpired as exc:
            target.unlink(missing_ok=True)
            raise LpError("LPUNPACK_TIMEOUT") from exc
        if completed.returncode or not target.is_file() or target.stat().st_size != partition["size"]:
            target.unlink(missing_ok=True)
            raise LpError("LPUNPACK_FAILED_OR_SIZE_MISMATCH")
        extents = inventory["extents"][partition["first_extent_index"]:
                                       partition["first_extent_index"] + partition["extent_count"]]
        results.append({
            "source_image_sha256": source_image_sha256,
            "source_super_sha256": source_sha256,
            "metadata_slot": metadata_slot if metadata_slot is not None else slot,
            "logical_partition_name": name,
            "group_name": partition["group_name"],
            "attributes": partition["attributes"],
            "extent_count": len(extents), "extent_mapping": extents,
            "derived_partition_path": str(target),
            "derived_partition_sha256": file_sha256(target),
            "filesystem_type": probe_filesystem(target),
            "tool": "lpunpack", "tool_version": TOOL_VERSION,
        })
    metrics = {"partition_count": inventory["partition_count"],
               "selected_partition_count": len(selected),
               "extracted_bytes": sum(int(p["size"]) for p in selected),
               "metadata_parse_seconds": inventory.get("metadata_parse_seconds"),
               "extraction_seconds": round(time.monotonic() - started, 3)}
    return results, metrics
