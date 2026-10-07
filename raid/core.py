# SPDX-License-Identifier: AGPL-3.0-or-later
"""Complete, clean MD v1 member sets -> deterministic read-only logical view.

No host-device scan, mounts, kernel assembly, resync, writes to evidence or AI.
The upstream metadata parser and stripe mapper are reused. Unsupported states
fail closed; a readable filesystem alone is never proof of the selected layout.
"""
from __future__ import annotations

from collections import OrderedDict
from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import struct
import threading

from . import PARSER_VERSION
from . import vendor

SECTOR = 512
MAX_MEMBERS = 32
MAX_DEVICES = 64
MAX_REQUEST = 8 * 1024 * 1024
MAX_SECTOR = (1 << 64) - 1


class RaidError(ValueError):
    """Safe machine code, deliberately excluding evidence text and secrets."""


def digest_json(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     separators=(",", ":")).encode()).hexdigest()


def confined_open(root: Path, relative: str):
    """Walk with directory fds: no absolute paths, traversal or symlink races."""
    if not isinstance(relative, str) or not relative or "\\" in relative or "\0" in relative:
        raise RaidError("INVALID_MEMBER_PATH")
    path = PurePosixPath(relative)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in relative.split("/")):
        raise RaidError("INVALID_MEMBER_PATH")
    if not hasattr(os, "O_NOFOLLOW"):
        raise RaidError("PLATFORM_CONFINEMENT_UNAVAILABLE")
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_fd
        fd = os.open(path.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise RaidError("MEMBER_NOT_REGULAR_FILE")
        return os.fdopen(fd, "rb")
    except OSError as exc:
        raise RaidError("MEMBER_PATH_UNAVAILABLE_OR_SYMLINK") from exc
    finally:
        os.close(directory)


def fingerprint(handle) -> tuple:
    info = os.fstat(handle.fileno())
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def hash_handle(handle, *, cancelled=lambda: False, deadline=None) -> str:
    hashed = hashlib.sha256()
    offset = 0
    while True:
        if cancelled():
            raise RaidError("EXPORT_CANCELLED")
        if deadline is not None:
            import time
            if time.monotonic() >= deadline:
                raise RaidError("EXPORT_TIMEOUT")
        chunk = os.pread(handle.fileno(), MAX_REQUEST, offset)
        if not chunk:
            return hashed.hexdigest()
        hashed.update(chunk)
        offset += len(chunk)


def _metadata_guard(handle, md):
    """Bound dynamic role array and check checksum BEFORE cstruct parsing."""
    sector, major, _ = md.find_super_block(handle)
    if sector is None:
        raise RaidError("NO_SUPPORTED_MD_METADATA")
    if major != 1:
        raise RaidError("MD_090_REQUIRES_SEPARATE_VALIDATION")
    if sector != 8:
        raise RaidError("MD_V1_METADATA_LOCATION_NOT_VALIDATED")
    handle.seek(sector * SECTOR)
    header = handle.read(256)
    if len(header) != 256:
        raise RaidError("TRUNCATED_MD_METADATA")
    max_dev = struct.unpack_from("<I", header, 220)[0]
    dev_number = struct.unpack_from("<I", header, 160)[0]
    if not 1 <= max_dev <= MAX_DEVICES or dev_number >= max_dev:
        raise RaidError("MD_ROLE_TABLE_LIMIT_OR_INVALID")
    roles = handle.read(max_dev * 2)
    if len(roles) != max_dev * 2:
        raise RaidError("TRUNCATED_MD_ROLE_TABLE")
    raw = bytearray(header + roles)
    checksum = struct.unpack_from("<I", raw, 216)[0]
    struct.pack_into("<I", raw, 216, 0)
    word_bytes = len(raw) // 4 * 4
    total = sum(word[0] for word in struct.iter_unpack("<I", raw[:word_bytes]))
    if len(raw) % 4:
        total += struct.unpack_from("<H", raw, word_bytes)[0]
    computed = ((total & 0xffffffff) + (total >> 32)) & 0xffffffff
    if computed != checksum:
        raise RaidError("MD_METADATA_CHECKSUM_MISMATCH")
    if struct.unpack_from("<Q", header, 144)[0] != sector:
        raise RaidError("MD_SUPER_OFFSET_MISMATCH")
    return sector * SECTOR


class RaidSession:
    """One explicit array, held source descriptors, locked seek/read operations."""

    def __init__(self, inbox: Path, members: list[dict]):
        self._stack = ExitStack()
        self._lock = threading.RLock()
        self._verified_stripes = OrderedDict()
        self._closed = False
        self.inbox = Path(inbox).resolve(strict=True)
        self.members = []
        self._handles = []
        self._fingerprints = []
        self._initial_hashes = None
        try:
            self._open(members)
        except Exception:
            self.close()
            raise

    def _open(self, members):
        if not isinstance(members, list) or not 2 <= len(members) <= MAX_MEMBERS:
            raise RaidError("MEMBER_COUNT_OUT_OF_RANGE")
        self.__input_members = [{"files": list(m["files"])} for m in members
                                if isinstance(m, dict) and isinstance(m.get("files"), list)]
        md = vendor.volume()
        seen = set()
        disks = []
        for member in members:
            if not isinstance(member, dict) or set(member) != {"files"}:
                raise RaidError("INVALID_MEMBER_SELECTION")
            files = member["files"]
            if not isinstance(files, list) or not 1 <= len(files) <= 256:
                raise RaidError("INVALID_SEGMENT_SELECTION")
            handles = [self._stack.enter_context(confined_open(self.inbox, name)) for name in files]
            for handle in handles:
                identity = fingerprint(handle)[:2]
                if identity in seen:
                    raise RaidError("DUPLICATE_SOURCE_FILE")
                seen.add(identity)
                self._handles.append(handle)
                self._fingerprints.append(fingerprint(handle))
            header = os.pread(handles[0].fileno(), 8, 0)
            if header == b"EVF\x09\x0d\x0a\xff\x00":
                # Do not let the existing reader glob additional evidence files.
                from .ewf import open_explicit
                logical = open_explicit(handles)
                self._stack.callback(logical.close)
                container = "EWF_E01"
            else:
                if len(handles) != 1:
                    raise RaidError("RAW_SPLIT_REQUIRES_SEPARATE_ADAPTER")
                logical = handles[0]
                container = "RAW"
            logical.seek(0, io.SEEK_END)
            logical_size = logical.tell()
            sb_offset = _metadata_guard(logical, md)
            disk = md.MDPhysicalDisk(logical)
            self.members.append({"files": list(files), "container": container,
                                 "logical_size": logical_size, "metadata_offset": sb_offset,
                                 "role": disk.raid_disk, "device_uuid": str(disk.device_uuid),
                                 "events": disk.events, "data_offset": disk.offset,
                                 "data_size": disk.size})
            disks.append(disk)
        self.disks = sorted(disks, key=lambda disk: disk.raid_disk if disk.raid_disk is not None else MAX_DEVICES)
        ref = self.disks[0]
        if ref.level not in (0, 1, 5):
            raise RaidError("RAID_LEVEL_NOT_VALIDATED")
        if ref.level == 5 and ref.layout not in (0, 1, 2, 3, 4, 5):
            raise RaidError("RAID5_LAYOUT_NOT_SUPPORTED")
        if ref.level == 0 and ref.layout not in (0, 1, 2):
            raise RaidError("RAID0_LAYOUT_NOT_SUPPORTED")
        if not 2 <= ref.raid_disks <= MAX_MEMBERS or (ref.level == 5 and ref.raid_disks < 3):
            raise RaidError("INVALID_ARRAY_MEMBER_COUNT")
        if any(not 0 <= disk.sb.dev_roles[disk.dev_number] < disk.raid_disks or
               disk.sb.dev_roles[disk.dev_number] != disk.raid_disk for disk in disks):
            raise RaidError("INCOMPLETE_OR_SPARE_MEMBER_SET")
        consensus = lambda disk: (disk.set_uuid, disk.level, disk.layout, disk.raid_disks,
                                   disk.chunk_size, disk.sb.size, disk.events,
                                   tuple(disk.sb.dev_roles))
        if any(consensus(disk) != consensus(ref) for disk in disks):
            raise RaidError("MD_METADATA_CONFLICT")
        roles = [disk.raid_disk for disk in disks]
        if len(set(roles)) != len(roles):
            raise RaidError("DUPLICATE_MEMBER_ROLE")
        if set(roles) != set(range(ref.raid_disks)):
            raise RaidError("INCOMPLETE_OR_SPARE_MEMBER_SET")
        if len({disk.device_uuid for disk in disks}) != len(disks):
            raise RaidError("DUPLICATE_DEVICE_UUID")
        for disk, member in zip(disks, self.members):
            # Bitmap, recovery, reshape, journal, bad-block and unknown features
            # need dedicated validation; no automatic host mdadm recovery.
            if disk.sb.feature_map != 0:
                raise RaidError("MD_FEATURE_NOT_VALIDATED")
            if disk.sb.resync_offset != MAX_SECTOR:
                raise RaidError("MD_NOT_CLEAN_OR_RESYNC_INCOMPLETE")
            if disk.data_offset * SECTOR < member["metadata_offset"] + 256 + disk.sb.max_dev * 2 and \
                    disk.data_offset * SECTOR + disk.data_size * SECTOR > member["metadata_offset"]:
                raise RaidError("MD_METADATA_OVERLAPS_DATA")
            if disk.data_offset * SECTOR + disk.data_size * SECTOR > member["logical_size"]:
                raise RaidError("TRUNCATED_MEMBER_DATA")
            if disk.sb.size <= 0 or disk.sb.size > disk.data_size:
                raise RaidError("INVALID_COMPONENT_SIZE")
        if ref.level in (0, 5) and (ref.chunk_size < SECTOR or ref.chunk_size > MAX_REQUEST or
                                  ref.chunk_size & (ref.chunk_size - 1)):
            raise RaidError("INVALID_CHUNK_SIZE")
        if len({disk.data_size for disk in disks}) != 1:
            raise RaidError("UNEQUAL_MEMBER_SIZE_NOT_VALIDATED")
        self.virtual = md.MDVirtualDisk(self.disks)
        # Linux MD v1 size is COMPONENT sectors, not RAID5 logical sectors.
        component = ref.sb.size * SECTOR
        if ref.level in (0, 5) and component % ref.chunk_size:
            raise RaidError("UNALIGNED_COMPONENT_SIZE")
        self.size = component * (ref.raid_disks if ref.level == 0 else
                                 ref.raid_disks - 1 if ref.level == 5 else 1)
        self.virtual.size = self.size
        # Physical tails are not array data. Enforce component-size boundaries.
        for disk in self.disks:
            disk.size = component
        if ref.level == 5:
            from dissect.volume.raid.stream import RAID456Stream

            class BoundedRAID5Stream(RAID456Stream):
                # Local AGPL adaptation: upstream _read reads `length` where
                # only `read_length` belongs to this stripe. Preserve mapper.
                def _read(self, offset, length):
                    chunks = []
                    while length:
                        stripe, within, role, _, _, _ = self._get_stripe_read_info(offset)
                        count = min(length, self.virtual_disk.stripe_size - within)
                        start, disk = self.disk_map[role]
                        disk.fh.seek(disk.offset + start + stripe * self.virtual_disk.stripe_size + within)
                        data = disk.fh.read(count)
                        if len(data) != count:
                            raise RaidError("SHORT_MEMBER_READ")
                        chunks.append(data)
                        length -= count
                        offset += count
                    return b"".join(chunks)

            self.stream = BoundedRAID5Stream(self.virtual)
        else:
            self.stream = self.virtual.open()
        self._stack.callback(self.stream.close)
        self.level = int(ref.level)
        self.chunk_size = ref.chunk_size
        self.layout = ref.layout
        self.uuid = str(ref.set_uuid)
        self.members.sort(key=lambda item: item["role"])
        self.check_unchanged()

    def check_unchanged(self):
        if self._closed:
            raise RaidError("RAID_SESSION_CLOSED")
        for handle, before in zip(self._handles, self._fingerprints):
            if fingerprint(handle) != before:
                raise RaidError("SOURCE_CHANGED")
        # Detect replacement/unlink as well as edits to held descriptors.
        i = 0
        for member in self._input_members:
            for name in member["files"]:
                with confined_open(self.inbox, name) as reopened:
                    if fingerprint(reopened) != self._fingerprints[i]:
                        raise RaidError("SOURCE_CHANGED")
                i += 1

    @property
    def _input_members(self):
        return self.__input_members

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self._stack.close()
        self._closed = True

    def _check_parity(self, offset, length):
        stripe_bytes = self.chunk_size * (len(self.disks) - 1)
        first, last = offset // stripe_bytes, (offset + length - 1) // stripe_bytes
        for stripe in range(first, last + 1):
            if stripe in self._verified_stripes:
                continue
            value = 0
            for disk in self.disks:
                disk.fh.seek(disk.offset + stripe * self.chunk_size)
                data = disk.fh.read(self.chunk_size)
                if len(data) != self.chunk_size:
                    raise RaidError("SHORT_MEMBER_READ")
                value ^= int.from_bytes(data, "little")
            if value:
                raise RaidError("RAID5_PARITY_MISMATCH")
            self._verified_stripes[stripe] = None
            if len(self._verified_stripes) > 128:
                self._verified_stripes.popitem(last=False)

    def read_at(self, offset: int, length: int) -> bytes:
        if any(not isinstance(v, int) or isinstance(v, bool) for v in (offset, length)) or \
                offset < 0 or length < 0 or length > MAX_REQUEST or offset + length > self.size:
            raise RaidError("LOGICAL_READ_OUT_OF_RANGE")
        with self._lock:
            self.check_unchanged()
            if not length:
                return b""
            if self.level == 5:
                self._check_parity(offset, length)
            self.stream.seek(offset)
            result = self.stream.read(length)
            if len(result) != length:
                raise RaidError("SHORT_LOGICAL_READ")
            if self.level == 1:
                for disk in self.disks:
                    disk.fh.seek(disk.offset + offset)
                    if disk.fh.read(length) != result:
                        raise RaidError("RAID1_MIRROR_CONFLICT")
            self.check_unchanged()
            return result

    def source_hashes(self, *, recheck=False, cancelled=lambda: False, deadline=None):
        with self._lock:
            self.check_unchanged()
            hashes = [hash_handle(handle, cancelled=cancelled, deadline=deadline) for handle in self._handles]
            self.check_unchanged()
            if recheck and self._initial_hashes is not None and hashes != self._initial_hashes:
                raise RaidError("SOURCE_CHANGED")
            self._initial_hashes = hashes
            by_name = {}
            i = 0
            for member in self._input_members:
                for name in member["files"]:
                    by_name[name] = hashes[i]
                    i += 1
            return by_name

    def manifest(self, hashes=None):
        layout = {"metadata": "linux_md_v1.2", "array_uuid": self.uuid,
                  "level": self.level, "layout": self.layout,
                  "chunk_size": self.chunk_size, "logical_size": self.size,
                  "members": self.members}
        return {"schema_version": 1, "parser_version": PARSER_VERSION,
                "source_type": "raid_logical_view", "source_root": str(self.inbox),
                "status": "READY_READONLY",
                "layout": layout, "layout_sha256": digest_json(layout),
                "source_sha256": hashes, "source_integrity": "FULL_SHA256" if hashes else "NOT_CALCULATED",
                "validation": {"metadata_checksums": "PASS", "complete_member_set": True,
                               "content": "CHECKED_ON_READ", "missing_member_recovery": False},
                "warnings": ["REAL_SAMPLE_REQUIRED", "TB_SCALE_NOT_VALIDATED"],
                "local_adaptations": ["RAID5_STRIPE_READ_LENGTH", "MD_V1_COMPONENT_CAPACITY"] +
                    (["EWF_STRICT_CHUNK_READS"] if any(m["container"] == "EWF_E01" for m in self.members) else []),
                "upstream_commits": {p["name"]: p["commit"] for p in
                    json.loads((vendor.ROOT / "sources.lock.json").read_text())["projects"]
                    if p["name"] in {"dissect.volume", "dissect.util", "dissect.cstruct-4.7"} or
                    (p["name"] == "qnxprobe" and any(m["container"] == "EWF_E01" for m in self.members))}}
