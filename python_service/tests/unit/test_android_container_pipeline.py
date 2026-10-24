"""Fail-closed sparse/LP probes; all mutated images are synthetic fixtures."""

import hashlib
import struct
import subprocess
import zlib

import pytest

from httpserver.services.android_sparse_image import (
    validate_sparse, normalize_sparse, file_sha256, SparseError, SPARSE_MAGIC,
)
from httpserver.services.android_lp_image import inspect_super, tool_root

# These probes drive the real AOSP LP toolchain (lpmake/lpunpack/libsparse)
# built by scripts/install_android_container_tools.sh from pinned sources.
# The toolchain is a build prerequisite of this suite, not an optional extra:
# the installer resolves the host's Android library packages by name (their
# versions differ per distro release) and records the resulting sources and
# binaries in the bundle manifest that verify_tools() checks. A missing
# toolchain therefore fails loudly with the command to run, instead of turning
# the LP coverage into silent skips.
def _aosp_tools_available() -> bool:
    bin_dir = tool_root() / "bin"
    return all((bin_dir / name).is_file()
               for name in ("lpmake", "lpunpack", "liblp.so", "lp_inventory"))


@pytest.fixture(scope="session", autouse=True)
def _require_aosp_toolchain():
    if not _aosp_tools_available():
        pytest.fail(
            "AOSP LP toolchain missing; build it with "
            "./scripts/install_android_container_tools.sh",
            pytrace=False,
        )


requires_aosp_tools = pytest.mark.usefixtures("_require_aosp_toolchain")


def sparse_bytes(*, blocks=3, chunks=None):
    if chunks is None:
        crc = zlib.crc32(b"A" * 4096 + b"B" * 4096 + bytes(4096))
        chunks = [
            struct.pack("<HHII", 0xCAC1, 0, 1, 12 + 4096) + b"A" * 4096,
            struct.pack("<HHII", 0xCAC2, 0, 1, 16) + b"B" * 4,
            struct.pack("<HHII", 0xCAC3, 0, 1, 12),
            struct.pack("<HHII", 0xCAC4, 0, 0, 16) + struct.pack("<I", crc),
        ]
    return struct.pack("<IHHHHIIII", SPARSE_MAGIC, 1, 0, 28, 12,
                       4096, blocks, len(chunks), 0) + b"".join(chunks)


def test_sparse_validates_every_standard_chunk(tmp_path):
    source = tmp_path / "fixture.sparse"
    source.write_bytes(sparse_bytes())
    row = validate_sparse(source)
    assert row["validation_status"] == "VALIDATED"
    assert row["analysis_state"] == "CAN_NORMALIZE_READY"
    assert (row["raw_chunks"], row["fill_chunks"], row["dont_care_chunks"],
            row["crc_chunks"]) == (1, 1, 1, 1)
    assert row["expanded_size"] == 3 * 4096


@pytest.mark.parametrize("name,mutate,error", [
    ("bad_magic", lambda b: bytes([0]) + b[1:], "BAD_MAGIC"),
    ("short_header", lambda b: b[:20], "TRUNCATED_HEADER"),
    ("invalid_chunk_type", lambda b: b[:28] + b"\x00\x00" + b[30:], "INVALID_CHUNK_TYPE"),
    ("chunk_size_overflow", lambda b: b[:32] + struct.pack("<I", 0xFFFFFFFF) + b[36:], "CHUNK_COUNT_OR_EXPANDED_OVERFLOW"),
    ("truncated_chunk", lambda b: b[:-2], "TRUNCATED_OR_INCONSISTENT_CHUNK"),
    ("trailing_bytes", lambda b: b + b"x", "CHUNK_COUNT_OR_TRAILING_BYTES_MISMATCH"),
    ("malformed_crc", lambda b: b[:-12] + struct.pack("<I", 1) + b[-8:], "MALFORMED_CRC_CHUNK"),
    ("crc_mismatch", lambda b: b[:-4] + b"\0" * 4, "CRC_MISMATCH"),
    ("count_mismatch", lambda b: b[:20] + struct.pack("<I", 5) + b[24:], "TRUNCATED_CHUNK_HEADER"),
])
def test_sparse_corruption_fails_closed(tmp_path, name, mutate, error):
    source = tmp_path / name
    source.write_bytes(mutate(sparse_bytes()))
    result = validate_sparse(source)
    assert result["validation_status"] != "VALIDATED"
    assert error in result["error"]


def test_sparse_expanded_size_limit(tmp_path):
    source = tmp_path / "bomb.sparse"
    source.write_bytes(struct.pack("<IHHHHIIII", SPARSE_MAGIC, 1, 0, 28, 12,
                                   1024 * 1024, 0xFFFFFFFF, 1, 0) +
                       struct.pack("<HHII", 0xCAC3, 0, 0xFFFFFFFF, 12))
    assert validate_sparse(source)["error"] == "SPARSE_BOMB_OR_EXPANDED_LIMIT"


@requires_aosp_tools
def test_sparse_normalizes_validated_image_to_exact_expanded_bytes(tmp_path):
    # The happy path had no coverage: only pre-conversion refusals were probed,
    # so a crash in the success record (a stale tool-version reference) went
    # unnoticed. This drives simg2img end to end and checks the bytes.
    source = tmp_path / "fixture.sparse"
    source.write_bytes(sparse_bytes())
    inventory = validate_sparse(source)
    target = tmp_path / "derived.raw"
    record = normalize_sparse(source, target, inventory,
                              expected_sha256=file_sha256(source))
    expected = b"A" * 4096 + b"B" * 4096 + bytes(4096)
    assert target.read_bytes() == expected
    assert record["derived_size"] == len(expected) == inventory["expanded_size"]
    assert record["source_sha256"] == file_sha256(source)
    assert record["derived_sha256"] == file_sha256(target)
    assert record["tool"] == "simg2img" and record["tool_version"]


@requires_aosp_tools
def test_sparse_refuses_insufficient_workspace_before_conversion(tmp_path, monkeypatch):
    source = tmp_path / "fixture.sparse"
    source.write_bytes(sparse_bytes())
    inventory = validate_sparse(source)
    monkeypatch.setattr("httpserver.services.android_sparse_image.shutil.disk_usage",
                        lambda _: type("Disk", (), {"free": 0})())
    target = tmp_path / "derived.raw"
    with pytest.raises(SparseError, match="INSUFFICIENT_WORKSPACE"):
        normalize_sparse(source, target, inventory, expected_sha256=file_sha256(source))
    assert not target.exists()


@pytest.fixture
def super_image(tmp_path):
    bin_dir = tool_root() / "bin"
    images = {}
    for name, letter in (("system_a", b"S"), ("vendor_a", b"V"), ("product_a", b"P")):
        target = tmp_path / f"{name}.img"
        with target.open("wb") as sink:
            sink.write(letter * 4096)
            sink.truncate(8 * 1024 * 1024)
        images[name] = target
    super_file = tmp_path / "super.raw"
    command = [str(bin_dir / "lpmake"), "--metadata-size", "65536",
               "--metadata-slots", "2", "--device-size", "67108864",
               "--group", "main_a:50331648"]
    for name, path in images.items():
        command += ["--partition", f"{name}:readonly:8388608:main_a",
                    "--image", f"{name}={path}"]
    command += ["--output", str(super_file)]
    run = subprocess.run(command, capture_output=True, timeout=120, check=False)
    assert run.returncode == 0, run.stderr[-500:]
    return super_file


@requires_aosp_tools
def test_lp_metadata_inventory_and_slot(super_image):
    row = inspect_super(super_image, 0)
    assert row["status"] == "ANDROID_SUPER" and row["ready"]
    assert row["metadata_version"] == [10, 0]
    assert row["metadata_slot_count"] == 2
    assert [item["name"] for item in row["partitions"]] == [
        "system_a", "vendor_a", "product_a"]
    assert row["active_slot"] == "ACTIVE_SLOT_UNKNOWN"


def test_lp_invalid_geometry_fails_closed(super_image):
    with super_image.open("r+b") as image:
        for offset in (4096, 8192):
            image.seek(offset + 8)
            image.write(b"\xff")
    assert inspect_super(super_image)["status"] == "MALFORMED_SUPER"


def test_lp_broken_metadata_checksum_fails_closed(super_image):
    with super_image.open("r+b") as image:
        for offset in (12288, 12288 + 2 * 65536):
            image.seek(offset + 12)
            image.write(b"\xff")
    assert inspect_super(super_image)["status"] == "MALFORMED_SUPER"


def test_lp_extent_past_image_end_fails_closed(super_image):
    with super_image.open("r+b") as image:
        image.truncate(12 * 1024 * 1024)
    assert inspect_super(super_image)["status"] == "MALFORMED_SUPER"


def _rewrite_extent_source(image, source_index):
    # Synthetic fixture only: recompute AOSP LP table/header SHA256 so our
    # extent-source check is exercised beyond the checksum gate.
    for base in (12288, 12288 + 2 * 65536):
        with image.open("r+b") as handle:
            handle.seek(base)
            header = bytearray(handle.read(128))
            header_size = struct.unpack_from("<I", header, 8)[0]
            table_size = struct.unpack_from("<I", header, 44)[0]
            handle.seek(base + header_size)
            tables = bytearray(handle.read(table_size))
            extent_offset = struct.unpack_from("<I", header, 92)[0]
            struct.pack_into("<I", tables, extent_offset + 20, source_index)
            handle.seek(base + header_size)
            handle.write(tables)
            header[48:80] = hashlib.sha256(tables).digest()
            header[12:44] = b"\0" * 32
            header[12:44] = hashlib.sha256(header[:header_size]).digest()
            handle.seek(base)
            handle.write(header)


def test_lp_invalid_extent_source_fails_closed(super_image):
    _rewrite_extent_source(super_image, 999)
    assert inspect_super(super_image)["status"] == "MALFORMED_SUPER"


def test_lp_unsupported_metadata_version_fails_closed(super_image):
    for base in (12288, 12288 + 2 * 65536):
        with super_image.open("r+b") as image:
            image.seek(base)
            header = bytearray(image.read(128))
            struct.pack_into("<H", header, 4, 11)
            header[12:44] = b"\0" * 32
            header[12:44] = hashlib.sha256(header).digest()
            image.seek(base)
            image.write(header)
    assert inspect_super(super_image)["status"] == "MALFORMED_SUPER"


@requires_aosp_tools
def test_lp_multi_device_requires_companion_input(tmp_path):
    source = tmp_path / "system_a.img"
    with source.open("wb") as sink:
        sink.write(b"S" * 4096)
        sink.truncate(8 * 1024 * 1024)
    output = tmp_path / "multi"
    output.mkdir()
    run = subprocess.run([str(tool_root() / "bin/lpmake"), "--metadata-size", "65536",
                          "--metadata-slots", "2", "--device", "super:67108864",
                          "--device", "extra:67108864", "--group", "main_a:50331648",
                          "--partition", "system_a:readonly:8388608:main_a",
                          "--image", f"system_a={source}", "--output", str(output)],
                         capture_output=True, timeout=120, check=False)
    assert run.returncode == 0
    inventory = inspect_super(output / "super_super.img")
    assert inventory["status"] == "ANDROID_SUPER"
    assert inventory["multi_device"] and not inventory["ready"]
    assert inventory["reason"] == "MULTI_DEVICE_SUPER_INPUT_REQUIRED"
