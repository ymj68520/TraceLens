"""Read-only preparation of cloud RAW export archives for the normal disk pipeline.

Standard library only: the C++ task worker also executes this module directly.
No archive member path is ever used as an extraction destination.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import tarfile
import time

VERSION = "aliyun-raw-export:v1"
MAX_RAW_BYTES = 2 * 1024**4
MAX_METADATA_BYTES = 65536
CHUNK = 8 * 1024**2


class ImageError(ValueError):
    pass


class BoundedTarInfo(tarfile.TarInfo):
    def _proc_member(self, archive):
        if self.type in (tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME,
                         tarfile.GNUTYPE_LONGLINK) and self.size > MAX_METADATA_BYTES:
            raise ImageError("ALIYUN_METADATA_LIMIT")
        if self.type == tarfile.GNUTYPE_SPARSE:
            raise ImageError("ALIYUN_SPARSE_TAR_UNSUPPORTED")
        return super()._proc_member(archive)


class LimitedReader:
    def __init__(self, source, limit):
        self.source, self.remaining = source, limit

    def read(self, size=-1):
        if size < 0 or size > self.remaining:
            raise ImageError("ALIYUN_METADATA_LIMIT")
        data = self.source.read(size)
        self.remaining -= len(data)
        return data


def _identity(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _open_source(path):
    path = Path(path)
    if path.is_symlink():
        raise ImageError("ALIYUN_SOURCE_SYMLINK")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    value = os.fstat(fd)
    if not stat.S_ISREG(value.st_mode):
        os.close(fd)
        raise ImageError("ALIYUN_SOURCE_NOT_REGULAR")
    return os.fdopen(fd, "rb"), value


def _validate_member(member):
    name = member.name
    if (not name or "\\" in name or ":" in name or
            PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts or
            any(ord(ch) < 32 for ch in name)):
        raise ImageError("ALIYUN_UNSAFE_MEMBER_PATH")
    if not member.isdir() and not member.isfile():
        raise ImageError("ALIYUN_LINK_OR_SPECIAL_MEMBER")
    if member.isdir() and member.size:
        raise ImageError("ALIYUN_DIRECTORY_PAYLOAD_REJECTED")
    if member.sparse is not None:
        raise ImageError("ALIYUN_SPARSE_TAR_UNSUPPORTED")


def _disk_prefix(data):
    # Format hypothesis only. ImageAnalyzer verifies partitions/filesystems next.
    return (len(data) >= 512 and data[510:512] == b"\x55\xaa") or (
        len(data) >= 1082 and data[1080:1082] == b"\x53\xef") or data[:4] == b"XFSB"


def inspect_header(path: Path) -> dict:
    """Bounded candidate detection, deliberately not a whole-archive CRC claim."""
    try:
        handle, before = _open_source(path)
        with handle, gzip.GzipFile(fileobj=handle) as gz, tarfile.open(
            fileobj=LimitedReader(gz, 256 * 1024), mode="r|", tarinfo=BoundedTarInfo,
        ) as archive:
            for index, member in enumerate(archive):
                if index >= 16:
                    raise ImageError("ALIYUN_METADATA_LIMIT")
                _validate_member(member)
                if member.isdir():
                    continue
                if not member.name.lower().endswith(".raw"):
                    return {"candidate": False}
                if member.size < 4096 or member.size > MAX_RAW_BYTES:
                    raise ImageError("ALIYUN_RAW_SIZE_LIMIT")
                if not _disk_prefix(archive.extractfile(member).read(4096)):
                    raise ImageError("ALIYUN_NOT_RAW_DISK")
                return {"candidate": True, "ready": True, "member_name": member.name,
                        "raw_size": member.size, "version": VERSION,
                        "validation": "header_only", "archive_crc_verified": False}
    except (OSError, EOFError, tarfile.TarError, ValueError) as error:
        return {"candidate": False, "ready": False,
                "reason": str(error) if isinstance(error, ImageError) else "ALIYUN_HEADER_UNREADABLE"}
    return {"candidate": False}


def normalize(source: Path, work: Path, expected_sha256: str, *, progress=None, cancelled=None) -> dict:
    """Publish one verified RAW and a provenance manifest, or leave neither."""
    source, work = Path(source), Path(work)
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        raise ImageError("ALIYUN_SOURCE_HASH_REQUIRED")
    if work.is_symlink() or source.is_symlink():
        raise ImageError("ALIYUN_SYMLINK_REJECTED")
    work.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        work.chmod(0o700)
    target, partial = work / "system.raw", work / "system.raw.partial"
    manifest_path = work / "source_manifest.json"
    temporary_manifest = work / "source_manifest.json.partial"
    if any(p.exists() or p.is_symlink() for p in (target, partial, manifest_path, temporary_manifest)):
        raise ImageError("ALIYUN_OUTPUT_EXISTS")
    digest, raw_digest = hashlib.sha256(), hashlib.sha256()
    written, entries, selected, raw_size = 0, 0, None, 0
    created = []
    started = time.monotonic()

    def check_cancelled():
        if cancelled and cancelled():
            raise ImageError("ALIYUN_CANCELLED")

    class HashReader:
        def read(self, size=-1):
            check_cancelled()
            data = handle.read(size)
            digest.update(data)
            return data

    handle, before = _open_source(source)
    try:
        with handle, gzip.GzipFile(fileobj=HashReader()) as gz:
            with tarfile.open(fileobj=gz, mode="r|", tarinfo=BoundedTarInfo) as archive:
                for member in archive:
                    check_cancelled()
                    entries += 1
                    if entries > 64:
                        raise ImageError("ALIYUN_MEMBER_LIMIT")
                    _validate_member(member)
                    if member.isdir():
                        continue
                    if selected is not None or not member.name.lower().endswith(".raw"):
                        raise ImageError("ALIYUN_EXPECT_SINGLE_RAW")
                    selected, raw_size = member.name, member.size
                    if raw_size < 4096 or raw_size > MAX_RAW_BYTES:
                        raise ImageError("ALIYUN_RAW_SIZE_LIMIT")
                    if shutil.disk_usage(work).free < raw_size + 512 * 1024**2:
                        raise ImageError("ALIYUN_INSUFFICIENT_SPACE")
                    payload = archive.extractfile(member)
                    with partial.open("xb") as sink:
                        created.append(partial)
                        while block := payload.read(CHUNK):
                            check_cancelled()
                            if written == 0 and not _disk_prefix(block[:4096]):
                                raise ImageError("ALIYUN_NOT_RAW_DISK")
                            raw_digest.update(block)
                            if block.strip(b"\0"):
                                sink.write(block)
                            else:
                                sink.seek(len(block), 1)
                            written += len(block)
                            if progress:
                                progress(written, raw_size)
                        sink.truncate(written)
                        sink.flush()
                        os.fsync(sink.fileno())
                    if written != raw_size:
                        raise ImageError("ALIYUN_TRUNCATED_RAW")
                buffered_tail = archive.fileobj.buf
                if buffered_tail.strip(b"\0"):
                    raise ImageError("ALIYUN_UNEXPECTED_TRAILING_DATA")
            # Consume trailing tar padding and ALL concatenated gzip members.
            trailing = 0
            while block := gz.read(CHUNK):
                check_cancelled()
                trailing += len(block)
                if block.strip(b"\0") or trailing > 16 * 1024**2:
                    raise ImageError("ALIYUN_UNEXPECTED_TRAILING_DATA")
            if selected is None:
                raise ImageError("ALIYUN_EXPECT_SINGLE_RAW")
            if (_identity(before) != _identity(os.fstat(handle.fileno())) or
                    _identity(before) != _identity(source.stat(follow_symlinks=False)) or
                    digest.hexdigest() != expected_sha256):
                raise ImageError("EVIDENCE_CHANGED_AFTER_PREFLIGHT")
        check_cancelled()
        os.link(partial, target)  # publish without overwriting any concurrent file
        created.append(target)
        partial.unlink()
        manifest = {"version": VERSION, "status": "verified", "source_path": str(source.resolve()),
                    "source_size": before.st_size, "source_sha256": digest.hexdigest(),
                    "member_name": selected, "raw_size": written, "raw_sha256": raw_digest.hexdigest(),
                    "derived_path": str(target.resolve()), "gzip_crc_verified": True,
                    "single_raw_verified": True, "elapsed_seconds": round(time.monotonic()-started, 3)}
        with temporary_manifest.open("x", encoding="utf-8") as sink:
            created.append(temporary_manifest)
            json.dump(manifest, sink, ensure_ascii=False, indent=2)
            sink.flush()
            os.fsync(sink.fileno())
        os.link(temporary_manifest, manifest_path)
        temporary_manifest.unlink()
        return manifest
    except BaseException:
        # Only files created by this attempt; never remove the source or pre-existing work.
        for path in created:
            path.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    import argparse
    import sys
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("work", type=Path)
    parser.add_argument("sha256")
    args = parser.parse_args()
    interrupted = [False]
    signal.signal(signal.SIGTERM, lambda *_: interrupted.__setitem__(0, True))
    last = [0.0]
    def emit_progress(done, total):
        if time.monotonic()-last[0] >= 2:
            print(json.dumps({"type": "progress", "done": done, "total": total}), flush=True)
            last[0] = time.monotonic()
    try:
        result = normalize(args.source, args.work, args.sha256, progress=emit_progress,
                           cancelled=lambda: interrupted[0])
        print(json.dumps({"type": "complete", "manifest": result}, ensure_ascii=False), flush=True)
    except Exception as error:
        code = str(error) if isinstance(error, ImageError) else "ALIYUN_ARCHIVE_INVALID_OR_IO_ERROR"
        print(json.dumps({"type": "error", "code": code}), flush=True)
        sys.exit(1)
