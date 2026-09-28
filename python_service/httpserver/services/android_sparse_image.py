"""Bounded AOSP Android sparse structural validator and read-only normalizer.

Only AOSP's packaged simg2img performs decoding. This module validates the
headers/chunk framing so a sparse bomb cannot reach that executable unchecked.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time
import zlib

SPARSE_MAGIC = 0xED26FF3A
CHUNKS = {0xCAC1: "RAW", 0xCAC2: "FILL", 0xCAC3: "DONT_CARE", 0xCAC4: "CRC32"}
MAX_EXPANDED_BYTES = 8 * 1024**4
MAX_CHUNKS = 1_000_000
MAX_HEADER_BYTES = 4096
MAX_CRC_VERIFY_BYTES = 8 * 1024**3
TOOL_VERSION = "android-sdk-libsparse-utils 1:10.0.0+r36-9"
TOOL_SHA256 = "ce77e6e736c3ac65b4f7457ac3d760154c1017762f73bc72f00c5a77dfce09f5"


class SparseError(ValueError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _initial(path: Path) -> dict:
    return {
        "source_size": path.stat().st_size, "expanded_size": None,
        "block_size": None, "chunk_count": None,
        "raw_chunks": 0, "fill_chunks": 0, "dont_care_chunks": 0,
        "crc_chunks": 0, "validation_status": "INVALID",
        "analysis_state": "DETECT_ONLY", "warnings": [],
    }


def _validate_crc(path: Path, file_hdr: int, chunk_hdr: int, chunks: int,
                  block: int, header_checksum: int) -> None:
    checksum = 0
    with path.open("rb") as source:
        source.seek(file_hdr)
        for _ in range(chunks):
            chunk_type, _, chunk_blocks, total_size = struct.unpack("<HHII", source.read(chunk_hdr)[:12])
            payload = total_size - chunk_hdr
            if chunk_type == 0xCAC1:
                remaining = payload
                while remaining:
                    data = source.read(min(1024 * 1024, remaining))
                    if not data:
                        raise SparseError("CRC_SOURCE_SHORT_READ")
                    checksum = zlib.crc32(data, checksum)
                    remaining -= len(data)
            elif chunk_type in (0xCAC2, 0xCAC3):
                pattern = source.read(4) if chunk_type == 0xCAC2 else b"\0" * 4
                unit = pattern * (1024 * 1024 // 4)
                remaining = chunk_blocks * block
                while remaining:
                    n = min(len(unit), remaining)
                    checksum = zlib.crc32(unit[:n], checksum)
                    remaining -= n
            elif chunk_type == 0xCAC4:
                actual = struct.unpack("<I", source.read(4))[0]
                if actual != checksum:
                    raise SparseError("CRC_MISMATCH")
    if header_checksum and header_checksum != checksum:
        raise SparseError("HEADER_CRC_MISMATCH")


def validate_sparse(path: Path) -> dict:
    """Validate *all* declared chunk boundaries without expanding the image."""
    path = Path(path)
    result = _initial(path)
    try:
        with path.open("rb") as source:
            header = source.read(28)
            if len(header) != 28:
                raise SparseError("TRUNCATED_HEADER")
            magic, major, minor, file_hdr, chunk_hdr, block, blocks, chunks, checksum = \
                struct.unpack("<IHHHHIIII", header)
            if magic != SPARSE_MAGIC:
                raise SparseError("BAD_MAGIC")
            if major != 1 or file_hdr < 28 or chunk_hdr < 12 or \
                    file_hdr > MAX_HEADER_BYTES or chunk_hdr > MAX_HEADER_BYTES:
                raise SparseError("UNSUPPORTED_SPARSE_HEADER")
            if block < 512 or block > 1024 * 1024 or block % 4:
                raise SparseError("INVALID_BLOCK_SIZE")
            if not blocks or not chunks or chunks > MAX_CHUNKS:
                raise SparseError("INVALID_DECLARED_COUNTS")
            expanded = block * blocks
            if expanded > MAX_EXPANDED_BYTES or expanded > max(result["source_size"], 1) * 1_000_000:
                raise SparseError("SPARSE_BOMB_OR_EXPANDED_LIMIT")
            result.update({"expanded_size": expanded, "block_size": block,
                           "chunk_count": chunks, "major_version": major,
                           "minor_version": minor, "file_header_size": file_hdr,
                           "chunk_header_size": chunk_hdr, "image_checksum": checksum,
                           "validation_status": "HEADER_VALID_ONLY",
                           "analysis_state": "CAN_ENUMERATE"})
            if checksum:
                result["warnings"].append("HEADER_CRC_NOT_VERIFIED_BY_STRUCTURAL_VALIDATOR")
            source.seek(file_hdr)
            total_blocks = 0
            for _ in range(chunks):
                at = source.tell()
                raw = source.read(chunk_hdr)
                if len(raw) != chunk_hdr:
                    raise SparseError("TRUNCATED_CHUNK_HEADER")
                chunk_type, reserved, chunk_blocks, total_size = struct.unpack("<HHII", raw[:12])
                if chunk_type not in CHUNKS or reserved != 0:
                    raise SparseError("INVALID_CHUNK_TYPE_OR_RESERVED")
                if chunk_type == 0xCAC4:
                    if chunk_blocks != 0:
                        raise SparseError("MALFORMED_CRC_CHUNK")
                    payload = 4
                else:
                    if not chunk_blocks or total_blocks + chunk_blocks > blocks:
                        raise SparseError("CHUNK_COUNT_OR_EXPANDED_OVERFLOW")
                    total_blocks += chunk_blocks
                    payload = chunk_blocks * block if chunk_type == 0xCAC1 else \
                        4 if chunk_type == 0xCAC2 else 0
                if total_size != chunk_hdr + payload or at + total_size > result["source_size"]:
                    raise SparseError("TRUNCATED_OR_INCONSISTENT_CHUNK")
                result[{0xCAC1: "raw_chunks", 0xCAC2: "fill_chunks",
                        0xCAC3: "dont_care_chunks", 0xCAC4: "crc_chunks"}[chunk_type]] += 1
                source.seek(at + total_size)
            if total_blocks != blocks or source.tell() != result["source_size"]:
                raise SparseError("CHUNK_COUNT_OR_TRAILING_BYTES_MISMATCH")
            if result["crc_chunks"] or checksum:
                if expanded > MAX_CRC_VERIFY_BYTES:
                    raise SparseError("CRC_VERIFICATION_SIZE_LIMIT")
                _validate_crc(path, file_hdr, chunk_hdr, chunks, block, checksum)
                result["crc_verified"] = True
                result["warnings"] = [item for item in result["warnings"]
                                      if item != "HEADER_CRC_NOT_VERIFIED_BY_STRUCTURAL_VALIDATOR"]
            result["validation_status"] = "VALIDATED"
            result["analysis_state"] = "CAN_NORMALIZE_READY"
    except (OSError, SparseError) as exc:
        result["error"] = str(exc)
        if result["validation_status"] == "HEADER_VALID_ONLY":
            result["validation_status"] = "MALFORMED_SPARSE"
    return result


def verify_tool() -> None:
    path = Path("/usr/bin/simg2img")
    if not path.is_file() or file_sha256(path) != TOOL_SHA256:
        raise SparseError("AOSP_SIMG2IMG_VERSION_MISMATCH")
    version = subprocess.run(["/usr/bin/dpkg-query", "-W", "-f=${Version}",
                              "android-sdk-libsparse-utils"],
                             capture_output=True, text=True, timeout=10, check=False)
    if version.returncode or version.stdout.strip() != "1:10.0.0+r36-9":
        raise SparseError("AOSP_SIMG2IMG_PACKAGE_MISMATCH")


def normalize_sparse(source: Path, output: Path, inventory: dict,
                     *, expected_sha256: str) -> dict:
    """Only write one derived raw in a caller-owned work directory."""
    source, output = Path(source).resolve(strict=True), Path(output)
    if inventory.get("validation_status") != "VALIDATED":
        raise SparseError("SPARSE_NOT_VALIDATED")
    verify_tool()
    if file_sha256(source) != expected_sha256:
        raise SparseError("EVIDENCE_CHANGED_AFTER_PREFLIGHT")
    parent = output.parent.resolve(strict=True)
    if output.is_symlink() or output.exists() or source == output.resolve(strict=False):
        raise SparseError("OUTPUT_EXISTS_OR_OVERLAPS_SOURCE")
    expanded = int(inventory["expanded_size"])
    reserve = max(256 * 1024 * 1024, expanded // 20)
    if shutil.disk_usage(parent).free < expanded + reserve:
        raise SparseError("INSUFFICIENT_WORKSPACE")
    started = time.monotonic()
    try:
        completed = subprocess.run(["/usr/bin/simg2img", str(source), str(output)],
                                   stdin=subprocess.DEVNULL, capture_output=True,
                                   timeout=3600, check=False)
    except subprocess.TimeoutExpired as exc:
        output.unlink(missing_ok=True)
        raise SparseError("SIMG2IMG_TIMEOUT") from exc
    if completed.returncode or not output.is_file() or output.stat().st_size != expanded:
        output.unlink(missing_ok=True)
        raise SparseError("SIMG2IMG_FAILED_OR_SIZE_MISMATCH")
    return {"tool": "simg2img", "tool_version": TOOL_VERSION,
            "source_sha256": expected_sha256, "source_size": source.stat().st_size,
            "source_format": "android_sparse", "derived_path": str(output.resolve()),
            "derived_size": output.stat().st_size, "derived_sha256": file_sha256(output),
            "conversion_seconds": round(time.monotonic() - started, 3),
            "bytes_written": expanded}
