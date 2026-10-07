# SPDX-License-Identifier: AGPL-3.0-or-later
"""Content-only, bounded RAID0/5 constraint search; never rank by filenames.

Only offset-zero, equal-sized RAW members and NTFS/FAT32 MBR/direct volumes are
searched. Search exhaustion and multiple candidates must remain explicit.
Parity is order-independent; it is NOT evidence of a unique disk ordering.
"""
from __future__ import annotations

from contextlib import ExitStack
import io
import os
import struct
import time

from .core import RaidError, digest_json
from .raw import RawRaidSession
from .filesystems import boot_spec, record, validate_fs, providers

CHUNKS = tuple(4096 << i for i in range(9))
SYSTEM_NAMES = ("$MFT", "$MFTMirr", "$LogFile", "$Volume", "$AttrDef", ".", "$Bitmap", "$Boot", "$BadClus")


def xp_record_domains(mapper, spec, domains, read):
    """Use entry numbers ONLY after resident $Volume identifies NTFS 3.1.

    Layout checked against TSK tsk_ntfs.h: ntfs_attr_vinfo version bytes 8/9;
    ntfs_mft.entry at byte 44 is XP-only, never apply this rule to NTFS 3.0.
    Dissect continues to perform USA/attribute/runlist decoding.
    """
    from dissect.ntfs.c_ntfs import ATTRIBUTE_TYPE_CODE
    rs, context = spec["record_size"], spec["context"]
    def mapping(offset):
        item = mapper.map_range(offset, 1)[0]
        return item["role"], item["source_offset"]
    location = spec["mft_offset"] + 3 * rs
    if location % mapper.chunk_size + rs > mapper.chunk_size: return
    role, offset = mapping(location)
    versions = []
    for member in domains[role]:
        try:
            volume = record(read(member, offset, rs), context)
            info = volume.attributes[ATTRIBUTE_TYPE_CODE.VOLUME_INFORMATION][0]
            if not info.resident: return
            data = info.header.open().read(12)
            versions.append(tuple(data[8:10]))
        except Exception: return
    if not versions or any(version != (3, 1) for version in versions): return
    role, offset = mapping(spec["mft_offset"])
    masters = []
    for member in domains[role]:
        try:
            master = record(read(member, offset, rs), context)
            masters.append((master.dataruns(), master.size()))
        except Exception: return
    if not masters or any(value != masters[0] for value in masters): return
    runs, size = masters[0]
    if len(runs) > 128 or size <= 0: return
    for index in range(16, min(size // rs, 2048), 31):
        byte = index * rs
        position = None
        for lcn, clusters in runs:
            run_bytes = clusters * context.cluster_size
            if byte < run_bytes:
                if lcn is not None: position = spec["base"] + lcn * context.cluster_size + byte
                break
            byte -= run_bytes
        if position is None or position + rs > mapper.size or position % mapper.chunk_size + rs > mapper.chunk_size:
            continue
        role, offset = mapping(position)
        good = set()
        for member in domains[role]:
            data = read(member, offset, rs)
            if not data.strip(b"\0"):  # not assumed allocated without the bitmap
                good.add(member)
                continue
            try:
                parsed = record(data, context)
                if parsed.header.MultiSectorHeader.UpdateSequenceArrayOffset >= 48 and \
                        (not parsed.header.Flags & 1 or struct.unpack_from("<I", data, 44)[0] == index):
                    good.add(member)
            except Exception: pass
        domains[role] &= good
        if not domains[role]: return


def enumerate_orders(domains, *, cap):
    """All-different CSP, minimal domain first; return bounded complete solutions."""
    result = []
    exhausted = False
    count = len(domains)
    def visit(assigned, used):
        nonlocal exhausted
        if exhausted: return
        if len(assigned) == count:
            if len(result) == cap:
                exhausted = True
            else:
                result.append([assigned[i] for i in range(count)])
            return
        role = min((r for r in range(count) if r not in assigned), key=lambda r: len(domains[r] - used))
        for member in sorted(domains[role] - used):
            visit({**assigned, role: member}, used | {member})
    visit({}, set())
    return result, exhausted


def infer(inbox, members, *, timeout=300, max_orders=4096, max_candidates=64):
    deadline = time.monotonic() + timeout
    start = time.monotonic()
    n = len(members)
    if not 2 <= n <= 16 or timeout <= 0 or not 1 <= max_orders <= 20000:
        raise RaidError("INFERENCE_LIMIT_OR_MEMBER_COUNT")
    providers()
    initial = {"level": 0, "layout": 0, "chunk_size": 4096, "order": list(range(n)), "data_offset": 0}
    cache = {}
    candidates = []
    limited = False
    tested = 0
    geometries = 0
    with RawRaidSession(inbox, members, initial) as source:
        source_revision = digest_json(source._fingerprints)
        handles = source._handles
        smallest = min(identity[2] for identity in source._fingerprints)
        def read(index, offset, length):
            if time.monotonic() > deadline:
                raise RaidError("INFERENCE_TIMEOUT")
            key = (index, offset, length)
            if key not in cache:
                if len(cache) >= 32000: cache.clear()
                cache[key] = os.pread(handles[index].fileno(), length, offset)
            return cache[key]
        anchors = []
        mbr_members = set()
        from dissect.volume.disk.schemes.mbr import MBR
        for i in range(n):
            prefix = read(i, 0, min(smallest, 1024**2))
            try:
                mbr = MBR(io.BytesIO(prefix[:512]))
                if any(p.type in (0x07, 0x0b, 0x0c) and p.offset > 0 for p in mbr.partitions):
                    mbr_members.add(i)
            except (ValueError, EOFError): pass
            except Exception: pass  # invalid source MBR is not a claimed partition
            for offset in range(0, len(prefix) - 511, 512):
                data = prefix[offset:offset + 512]
                if data[3:11] != b"NTFS    " and data[82:90] != b"FAT32   ": continue
                try:
                    spec = boot_spec(data)
                    if spec:
                        anchors.append((i, offset, spec))
                except Exception: pass
        # A quick parity check is used only to prune impossible RAID5 inputs.
        parity_possible = n >= 3
        for offset in (0, 4096, smallest // 4 // 4096 * 4096, smallest // 2 // 4096 * 4096):
            if not parity_possible: break
            value = 0
            for i in range(n): value ^= int.from_bytes(read(i, offset, 4096), "little")
            if value: parity_possible = False
        # A negative syndrome in sampled free/padding regions cannot establish
        # that a metadata-free set isn't RAID5. Keep it as a warning, not a veto.
        levels = [0] + ([5] if n >= 3 else [])
        for level in levels:
            for layout in ((0,) if level == 0 else (0, 1, 2, 3)):
                for chunk in CHUNKS:
                    if time.monotonic() > deadline: limited = True; break
                    plan = {**initial, "level": level, "layout": layout, "chunk_size": chunk}
                    with RawRaidSession(inbox, members, plan) as mapper:
                        def mapping(offset):
                            mapped = mapper.map_range(offset, 1)[0]
                            return mapped["role"], mapped["source_offset"]
                        for anchor_member, anchor_offset, spec in anchors:
                            if spec["base"] + spec["size"] > mapper.size + 512: continue
                            role, physical = mapping(spec["base"])
                            if physical != anchor_offset: continue
                            geometries += 1
                            domains = {r: set(range(n)) for r in range(n)}
                            domains[role] = {anchor_member}
                            if spec["base"]:
                                mbr_role, _ = mapping(0)
                                domains[mbr_role] &= mbr_members
                            if not all(domains.values()): continue
                            if spec["kind"] == "ntfs":
                                rs, context = spec["record_size"], spec["context"]
                                # Strong format constants anchor reserved MFT records.
                                for index, expected in enumerate(SYSTEM_NAMES):
                                    logical = spec["mft_offset"] + index * rs
                                    if logical + rs > mapper.size or logical % chunk + rs > chunk:
                                        continue  # split records are checked after assignment
                                    r, off = mapping(logical)
                                    valid = set()
                                    for member in domains[r]:
                                        try:
                                            entry = record(read(member, off, rs), context)
                                            if expected in entry.filenames(): valid.add(member)
                                        except Exception: pass
                                    domains[r] &= valid
                                    if not domains[r]: break
                                # NTFS's independently located MFT mirror also
                                # carries the first four reserved records.
                                for index, expected in enumerate(SYSTEM_NAMES[:4]):
                                    logical = spec["mirror_offset"] + index * rs
                                    if logical + rs > mapper.size or logical % chunk + rs > chunk:
                                        continue
                                    r, off = mapping(logical)
                                    valid = set()
                                    for member in domains[r]:
                                        try:
                                            if expected in record(read(member, off, rs), context).filenames():
                                                valid.add(member)
                                        except Exception: pass
                                    domains[r] &= valid
                                    if not domains[r]: break
                                if all(domains.values()):
                                    xp_record_domains(mapper, spec, domains, read)
                            else:
                                # Copies of a FAT must agree at the same entry index.
                                # Arc consistency constrains unknown physical roles.
                                if spec["fat_copies"] == 2:
                                    pairs = []
                                    stride = max(512, spec["fat_size"] // 96 // 512 * 512)
                                    for pos in range(0, spec["fat_size"], stride):
                                        a, ao = mapping(spec["fat_offset"] + pos)
                                        b, bo = mapping(spec["fat_offset"] + spec["fat_size"] + pos)
                                        length = min(512, chunk - ao % chunk, chunk - bo % chunk, spec["fat_size"] - pos)
                                        allowed = {(i, j) for i in domains[a] for j in domains[b]
                                                   if (a != b or i == j) and (a == b or i != j) and
                                                   read(i, ao, length) == read(j, bo, length)}
                                        pairs.append((a, b, allowed))
                                    for _ in range(n + 1):
                                        changed = False
                                        for a, b, allowed in pairs:
                                            da = {i for i in domains[a] if any((i, j) in allowed for j in domains[b])}
                                            db = {j for j in domains[b] if any((i, j) in allowed for i in domains[a])}
                                            changed |= da != domains[a] or db != domains[b]
                                            domains[a], domains[b] = da, db
                                        if not changed: break
                            if not all(domains.values()): continue
                            orders, capped = enumerate_orders(domains, cap=max_orders)
                            limited |= capped
                            for order in orders:
                                if time.monotonic() > deadline:
                                    limited = True; break
                                tested += 1
                                chosen = {**plan, "order": order}
                                try:
                                    with RawRaidSession(inbox, members, chosen, parity_mode="observe") as candidate:
                                        candidate._probe_defer_guards = True
                                        proof = validate_fs(candidate, spec)
                                        parity_mismatches = candidate.parity_mismatch_count
                                        candidate._probe_defer_guards = False
                                        candidate.check_unchanged()
                                    item = {"plan": chosen, "volume_offset": spec["base"],
                                            "filesystem": spec["kind"], "structure_validation": proof,
                                            "parity_mismatching_probe_requests": parity_mismatches,
                                            "content_reference_validation": "NOT_RUN"}
                                    item["candidate_id"] = digest_json({"plan": chosen, "volume_offset": spec["base"],
                                                                       "source_revision": source_revision})
                                    if not any(c["candidate_id"] == item["candidate_id"] for c in candidates):
                                        candidates.append(item)
                                    if len(candidates) >= max_candidates:
                                        limited = True; break
                                except Exception: pass
                            if len(candidates) >= max_candidates: break
        source.check_unchanged()
    status = ("SEARCH_LIMIT_REACHED" if limited else "UNIQUE_STRUCTURAL_CANDIDATE" if len(candidates) == 1 else
              "AMBIGUOUS" if candidates else "NO_SUPPORTED_CANDIDATE")
    return {"schema_version": 1, "status": status, "candidates": candidates, "source_revision": source_revision,
            "tested_orders": tested, "geometries_with_boot_anchors": geometries,
            "search_scope": {"levels": [0, 5], "layouts": [0, 1, 2, 3], "chunks": list(CHUNKS),
                             "data_offsets": [0], "filesystems": ["ntfs", "fat32"], "max_orders_per_geometry": max_orders},
            "runtime_seconds": time.monotonic() - start,
            "sampled_parity_consistent": parity_possible,
            "warnings": ["CONTENT_REFERENCE_VALIDATION_REQUIRED", "NO_FILENAME_ORDER_ASSUMPTION",
                         "SEARCH_SCOPE_IS_NOT_UNIVERSAL_RAID_SUPPORT"]}
