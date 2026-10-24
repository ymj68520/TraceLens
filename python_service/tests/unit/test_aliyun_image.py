import gzip
import hashlib
import io
import json
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpserver.services import aliyun_image as adapter, evidence_preflight as preflight


def disk():
    value = bytearray(16384)
    value[510:512] = b"\x55\xaa"
    value[512:520] = b"EFI PART"
    value[-512:] = b"Z" * 512
    return bytes(value)


def archive(path, entries=None, *, extra=False):
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, content, kind in entries or [("file_m-test_system.raw", disk(), tarfile.REGTYPE)]:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = len(content) if kind == tarfile.REGTYPE else 0
            if kind == tarfile.SYMTYPE: member.linkname = "/etc/passwd"
            tar.addfile(member, io.BytesIO(content) if member.isfile() else None)
    compressed = gzip.compress(payload.getvalue())
    if extra:
        compressed = compressed[:3] + bytes([compressed[3] | 4]) + compressed[4:10] + b"\x04\x00TL\x00\x00" + compressed[10:]
    path.write_bytes(compressed)
    return hashlib.sha256(compressed).hexdigest()


def test_extra_gzip_header_and_full_provenance(tmp_path):
    source = tmp_path / "cloud.raw.tar.gz"
    digest = archive(source, extra=True)
    assert adapter.inspect_header(source)["archive_crc_verified"] is False
    manifest = adapter.normalize(source, tmp_path / "work", digest)
    assert Path(manifest["derived_path"]).read_bytes() == disk()
    assert manifest["raw_sha256"] == hashlib.sha256(disk()).hexdigest()
    assert manifest["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert manifest["single_raw_verified"] and manifest["gzip_crc_verified"]
    assert json.loads((tmp_path / "work/source_manifest.json").read_text()) == manifest
    before = (tmp_path / "work/system.raw").read_bytes()
    with pytest.raises(adapter.ImageError, match="OUTPUT_EXISTS"):
        adapter.normalize(source, tmp_path / "work", digest)
    assert (tmp_path / "work/system.raw").read_bytes() == before


@pytest.mark.parametrize("entries,code", [
    ([("../escape.raw", disk(), tarfile.REGTYPE)], "UNSAFE_MEMBER"),
    ([("/absolute.raw", disk(), tarfile.REGTYPE)], "UNSAFE_MEMBER"),
    ([("C:\\escape.raw", disk(), tarfile.REGTYPE)], "UNSAFE_MEMBER"),
    ([("disk.raw", b"", tarfile.SYMTYPE)], "LINK_OR_SPECIAL"),
    ([("disk.raw", disk(), tarfile.REGTYPE), ("second.raw", disk(), tarfile.REGTYPE)], "SINGLE_RAW"),
    ([("disk.raw", b"not a disk" * 2000, tarfile.REGTYPE)], "NOT_RAW_DISK"),
    ([("notes.txt", b"text", tarfile.REGTYPE)], "SINGLE_RAW"),
])
def test_unsafe_or_ambiguous_exports_leave_no_published_raw(tmp_path, entries, code):
    source = tmp_path / "cloud.tar.gz"
    digest = archive(source, entries)
    with pytest.raises(adapter.ImageError, match=code):
        adapter.normalize(source, tmp_path / "work", digest)
    assert not list((tmp_path / "work").glob("*"))
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("damage", ["crc", "truncated", "hash"])
def test_bad_crc_truncation_and_changed_source_never_publish(tmp_path, damage):
    source = tmp_path / "cloud.tar.gz"
    expected = archive(source)
    value = bytearray(source.read_bytes())
    if damage == "crc": value[-8] ^= 1
    if damage == "truncated": value = value[:-4]
    source.write_bytes(value)
    if damage != "hash": expected = hashlib.sha256(value).hexdigest()
    else: expected = "a" * 64
    with pytest.raises((adapter.ImageError, OSError, EOFError, tarfile.TarError)):
        adapter.normalize(source, tmp_path / "work", expected)
    assert not list((tmp_path / "work").glob("*"))


def test_cancel_and_space_limit_preserve_source(tmp_path, monkeypatch):
    source = tmp_path / "cloud.tar.gz"
    digest = archive(source)
    flag = [False]
    with pytest.raises(adapter.ImageError, match="CANCELLED"):
        adapter.normalize(source, tmp_path / "cancel", digest,
                          progress=lambda *_: flag.__setitem__(0, True), cancelled=lambda: flag[0])
    assert not list((tmp_path / "cancel").glob("*"))
    monkeypatch.setattr(adapter.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    with pytest.raises(adapter.ImageError, match="INSUFFICIENT_SPACE"):
        adapter.normalize(source, tmp_path / "space", digest)
    assert source.read_bytes() and hashlib.sha256(source.read_bytes()).hexdigest() == digest


def test_nonzero_data_hidden_after_tar_end_is_rejected(tmp_path):
    source = tmp_path / "cloud.tar.gz"
    archive(source)
    plain = gzip.decompress(source.read_bytes()) + b"hidden payload"
    source.write_bytes(gzip.compress(plain))
    with pytest.raises(adapter.ImageError, match="TRAILING_DATA"):
        adapter.normalize(source, tmp_path / "work", hashlib.sha256(source.read_bytes()).hexdigest())
    assert not (tmp_path / "work/system.raw").exists()


def test_existing_preflight_recognizes_cloud_export_without_extracting(tmp_path, monkeypatch):
    source = tmp_path / "file_m-x_system.raw.tar.gz"
    digest = archive(source, extra=True)
    monkeypatch.setattr(preflight, "evidence_inbox", lambda: tmp_path)
    monkeypatch.setattr(preflight, "job_root", lambda: tmp_path / "jobs")
    candidate = next(row for row in preflight.list_candidates() if row["name"] == source.name)
    assert candidate["kind"] == "aliyun_raw_export"
    assert candidate["adapter"] == "aliyun-image"
    job = preflight.start_job(candidate["id"], full_hash=True)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = preflight.get_job(job["id"])
        if job["status"] not in {"queued", "running"}: break
        time.sleep(.02)
    assert job["status"] == "completed" and job["integrity_status"] == "verified"
    assert job["sha256"] == digest and job["aliyun_image"]["raw_size"] == len(disk())
    assert not list(tmp_path.rglob("*.raw"))


@pytest.mark.parametrize('kind,size,code', [
    (tarfile.XHDTYPE, adapter.MAX_METADATA_BYTES + 1, 'METADATA_LIMIT'),
    (tarfile.REGTYPE, adapter.MAX_RAW_BYTES + 512, 'RAW_SIZE_LIMIT'),
    (tarfile.DIRTYPE, 4096, 'DIRECTORY_PAYLOAD'),
])
def test_unbounded_headers_are_rejected_before_payload_allocation(tmp_path, kind, size, code):
    info=tarfile.TarInfo('system.raw');info.type=kind;info.size=size
    source=tmp_path/'bad.raw.tar.gz'
    source.write_bytes(gzip.compress(info.tobuf(format=tarfile.GNU_FORMAT)+b'\0'*1024))
    with pytest.raises(adapter.ImageError,match=code):
        adapter.normalize(source,tmp_path/'work',hashlib.sha256(source.read_bytes()).hexdigest())
    assert not (tmp_path/'work/system.raw').exists()
