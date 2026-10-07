# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicit metadata-free geometry. Never pretend operator parameters are MD metadata."""
from __future__ import annotations

import io
import json
import os

from .core import RaidSession, RaidError, MAX_MEMBERS, MAX_REQUEST, confined_open, fingerprint, digest_json
from . import vendor
from .streams import bounded_raid5


def validate_plan(plan, count):
    if not isinstance(plan, dict) or set(plan) != {"level", "layout", "chunk_size", "order", "data_offset"}:
        raise RaidError("INVALID_RAW_LAYOUT")
    if any(not isinstance(plan[key], int) or isinstance(plan[key], bool) for key in
           ("level", "layout", "chunk_size", "data_offset")):
        raise RaidError("INVALID_RAW_LAYOUT")
    if plan["level"] not in (0, 5) or (plan["level"] == 5 and count < 3):
        raise RaidError("RAW_RAID_LEVEL_NOT_SUPPORTED")
    if plan["layout"] not in (0, 1, 2, 3) or (plan["level"] == 0 and plan["layout"] != 0):
        raise RaidError("RAW_RAID_LAYOUT_NOT_SUPPORTED")
    chunk = plan["chunk_size"]
    if chunk < 4096 or chunk > 1024**2 or chunk & (chunk - 1) or plan["data_offset"] != 0:
        raise RaidError("RAW_CHUNK_OR_OFFSET_NOT_SUPPORTED")
    order = plan["order"]
    if not isinstance(order, list) or any(not isinstance(i, int) or isinstance(i, bool) for i in order) or \
            sorted(order) != list(range(count)):
        raise RaidError("INVALID_RAW_MEMBER_ORDER")


class RawRaidSession(RaidSession):
    def __init__(self, inbox, members, plan, *, inference=None, parity_mode="strict"):
        if parity_mode not in ("strict", "observe"):
            raise RaidError("INVALID_PARITY_POLICY")
        self.parity_mode = parity_mode
        self.parity_checks = 0
        self.parity_mismatch_count = 0
        self.parity_mismatch_ranges = []
        self.plan = json.loads(json.dumps(plan))  # freeze mutable caller containers
        self.inference = inference
        super().__init__(inbox, members)

    def _open(self, members):
        if not isinstance(members, list) or not 2 <= len(members) <= MAX_MEMBERS:
            raise RaidError("MEMBER_COUNT_OUT_OF_RANGE")
        validate_plan(self.plan, len(members))
        vendor.volume()
        from dissect.volume.raid.raid import PhysicalDisk, VirtualDisk
        self._RaidSession__input_members = []
        disks = []
        seen = set()
        for member in members:
            if not isinstance(member, dict) or set(member) != {"files"} or \
                    not isinstance(member["files"], list) or len(member["files"]) != 1:
                raise RaidError("RAW_SINGLE_FILE_MEMBERS_REQUIRED")
            files = list(member["files"])
            handle = self._stack.enter_context(confined_open(self.inbox, files[0]))
            identity = fingerprint(handle)
            if identity[:2] in seen:
                raise RaidError("DUPLICATE_SOURCE_FILE")
            seen.add(identity[:2])
            if os.pread(handle.fileno(), 8, 0) == b"EVF\x09\x0d\x0a\xff\x00":
                raise RaidError("METADATA_FREE_EWF_NOT_YET_VALIDATED")
            if identity[2] < 4096 or identity[2] % 512:
                raise RaidError("INVALID_RAW_MEMBER_SIZE")
            self._handles.append(handle)
            self._fingerprints.append(identity)
            self._RaidSession__input_members.append({"files": files})
            disks.append(PhysicalDisk(handle, 0, identity[2]))
        if len({disk.size for disk in disks}) != 1:
            raise RaidError("UNEQUAL_MEMBER_SIZE_NOT_VALIDATED")
        self.level, self.layout, self.chunk_size = self.plan["level"], self.plan["layout"], self.plan["chunk_size"]
        self.disks = [disks[i] for i in self.plan["order"]]
        component = disks[0].size // self.chunk_size * self.chunk_size
        self.tail_bytes = disks[0].size - component
        self.size = component * (len(disks) if self.level == 0 else len(disks) - 1)
        for disk in disks:
            disk.size = component
        self.virtual = VirtualDisk(None, None, self.size, self.level, self.layout,
                                   self.chunk_size, len(disks), {i: (0, disk) for i, disk in enumerate(self.disks)})
        self.stream = bounded_raid5(self.virtual) if self.level == 5 else self.virtual.open()
        self._stack.callback(self.stream.close)
        self.uuid = None  # no invented array UUID or device identifiers
        for role, index in enumerate(self.plan["order"]):
            self.members.append({"files": list(self._input_members[index]["files"]), "container": "RAW", "role": role,
                                 "device_uuid": None, "metadata_offset": None, "events": None,
                                 "logical_size": self._fingerprints[index][2], "data_offset": 0,
                                 "data_size": component, "input_index": index})
        self.check_unchanged()

    def map_range(self, offset, length, *, limit=4096):
        if offset < 0 or length < 0 or offset + length > self.size:
            raise RaidError("LOGICAL_READ_OUT_OF_RANGE")
        result = []
        while length:
            within = offset % self.chunk_size
            count = min(length, self.chunk_size - within)
            if self.level == 5:
                stripe, _, role, parity, _, _ = self.stream._get_stripe_read_info(offset)
            else:
                # Equal-sized single zone, exactly the geometry used by upstream.
                stripe, role = divmod(offset // self.chunk_size, len(self.disks))
                parity = None
            index = self.plan["order"][role]
            result.append({"logical_offset": offset, "length": count, "role": role,
                           "source_file": self._input_members[index]["files"][0],
                           "source_offset": stripe * self.chunk_size + within,
                           "parity_role": parity, "recovered_bytes": False})
            if len(result) > limit:
                raise RaidError("SOURCE_MAPPING_LIMIT")
            offset += count
            length -= count
        return result

    def _check_parity(self, offset, length):
        # For metadata-free sources no superblock establishes a fully synced
        # array. Check the requested bytes, not unrelated read-ahead padding.
        while length:
            stripe, within, _, _, _, _ = self.stream._get_stripe_read_info(offset)
            size = min(length, self.chunk_size - within)
            physical = stripe * self.chunk_size + within
            value = 0
            for disk in self.disks:
                disk.fh.seek(physical)
                data = disk.fh.read(size)
                if len(data) != size: raise RaidError("SHORT_MEMBER_READ")
                value ^= int.from_bytes(data, "little")
            self.parity_checks += 1
            if value:
                self.parity_mismatch_count += 1
                if len(self.parity_mismatch_ranges) < 128:
                    self.parity_mismatch_ranges.append({"source_offset": physical, "length": size})
                if self.parity_mode == "strict":
                    raise RaidError("RAID5_PARITY_MISMATCH")
            offset += size
            length -= size

    def check_unchanged(self):
        if not getattr(self, "_probe_defer_guards", False):
            return super().check_unchanged()

    def manifest(self, hashes=None):
        result = super().manifest(hashes)
        result["layout"]["metadata"] = None
        result["layout"]["parameter_origin"] = "CONTENT_CONSTRAINT_CANDIDATE" if self.inference else "EXPLICIT_OPERATOR_PARAMETERS"
        result["layout"]["unmapped_tail_per_member"] = self.tail_bytes
        result["layout_sha256"] = digest_json(result["layout"])
        result["validation"]["metadata_checksums"] = "NOT_PRESENT"
        result["validation"]["complete_member_set"] = None
        result["validation"]["selected_member_count"] = len(self.members)
        result["inference"] = self.inference
        result["validation"]["parity"] = {"policy": self.parity_mode,
            "checked_requests": self.parity_checks, "mismatching_requests": self.parity_mismatch_count,
            "mismatch_ranges": self.parity_mismatch_ranges, "recovered_bytes": False}
        if self.parity_mismatch_count:
            result["warnings"].append("RAID5_PARITY_MISMATCH_CONTENT_UNCONFIRMED")
        result["warnings"] += ["CONTENT_REFERENCE_VALIDATION_REQUIRED"]
        if self.tail_bytes:
            result["warnings"].append("MEMBER_TAIL_NOT_MAPPED")
        return result


class SessionIO(io.RawIOBase):
    """Independent file cursor over the locked logical reader; never writable."""
    def __init__(self, session, base=0, size=None):
        self.session = session
        self.base = base
        self.size = session.size - base if size is None else size
        self._pos = 0
        self.trace = []

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self._pos

    def seek(self, offset, whence=0):
        value = offset if whence == 0 else self._pos + offset if whence == 1 else self.size + offset if whence == 2 else -1
        if value < 0:
            raise RaidError("INVALID_LOGICAL_SEEK")
        self._pos = value
        return value

    def read(self, size=-1):
        size = max(0, self.size - self._pos) if size is None or size < 0 else min(size, max(0, self.size - self._pos))
        if size > MAX_REQUEST:
            raise RaidError("LOGICAL_READ_LIMIT")
        if not size: return b""
        offset = self.base + self._pos
        data = self.session.read_at(offset, size)
        self._pos += len(data)
        if len(self.trace) < 4096:
            self.trace.append({"logical_offset": offset, "length": len(data)})
        return data
