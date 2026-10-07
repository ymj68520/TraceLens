# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bounded structure validation using pinned Dissect NTFS/FAT implementations."""
from __future__ import annotations

import io
import struct

from . import vendor
from .core import RaidError
from .raw import SessionIO


def providers():
    vendor.volume()
    ntfs = vendor.load("dissect.ntfs", "dissect.ntfs.ntfs")
    fat = vendor.load("dissect.fat", "dissect.fat.fat")
    return ntfs, fat


def boot_spec(data):
    if len(data) != 512 or data[510:512] != b"\x55\xaa":
        return None
    sector = struct.unpack_from("<H", data, 11)[0]
    if sector != 512 or data[13] not in (1, 2, 4, 8, 16, 32, 64, 128):
        return None
    ntfs, fat = providers()
    base = struct.unpack_from("<I", data, 28)[0] * sector
    if data[3:11] == b"NTFS    ":
        record = struct.unpack_from("<b", data, 64)[0]
        if not -16 <= record <= 16 or record == 0:
            return None
        context = ntfs.NTFS(boot=io.BytesIO(data))
        size = context.boot_sector.NumberSectors * sector
        if not 512 <= context._record_size <= 65536 or size <= 0:
            return None
        return {"kind": "ntfs", "base": base, "size": size, "boot": data,
                "context": context, "cluster_size": context.cluster_size,
                "record_size": context._record_size,
                "mft_offset": base + context.boot_sector.MftStartLcn * context.cluster_size,
                "mirror_offset": base + context.boot_sector.Mft2StartLcn * context.cluster_size}
    if data[82:90] == b"FAT32   ":
        fat.validate_bpb(data)
        reserved = struct.unpack_from("<H", data, 14)[0]
        fats = data[16]
        fat_sectors = struct.unpack_from("<I", data, 36)[0]
        size = struct.unpack_from("<I", data, 32)[0] * sector
        if not 1 <= fats <= 2 or fat_sectors == 0 or size <= 0:
            return None
        return {"kind": "fat32", "base": base, "size": size, "boot": data,
                "fat_offset": base + reserved * sector, "fat_size": fat_sectors * sector,
                "fat_copies": fats}
    return None


def record(data, context):
    from dissect.ntfs.mft import MftRecord
    return MftRecord.from_bytes(data, ntfs=context)


def open_fs(session, spec):
    ntfs, fat = providers()
    stream = SessionIO(session, spec["base"], min(spec["size"], session.size - spec["base"]))
    fs = ntfs.NTFS(stream) if spec["kind"] == "ntfs" else fat.FATFS(stream)
    return fs, stream


def validate_fs(session, spec, *, limit=128):
    """Metadata cross-reference checks, NOT an independent full-content oracle."""
    fs, stream = open_fs(session, spec)
    if spec["kind"] == "ntfs":
        for index, expected in ((0, "$MFT"), (1, "$MFTMirr"), (2, "$LogFile"), (5, ".")):
            if expected not in fs.mft.get(index).filenames():
                raise RaidError("NTFS_SYSTEM_RECORD_MISMATCH")
        queue = [(fs.mft.get(5), 0)]
        seen = {5}
        count = 0
        while queue:
            parent, depth = queue.pop()
            if depth > 16:
                raise RaidError("FS_DIRECTORY_DEPTH_LIMIT")
            for entry in parent.iterdir(ignore_dos=True):
                node = entry.dereference()
                if entry.attribute.file_name not in node.filenames():
                    raise RaidError("NTFS_DIRECTORY_REFERENCE_MISMATCH")
                count += 1
                if count > limit:
                    return {"kind": "ntfs", "references_checked": count - 1, "truncated": True}
                if node.is_dir() and node.segment not in seen and entry.attribute.file_name not in (".", ".."):
                    seen.add(node.segment)
                    queue.append((node, depth + 1))
        return {"kind": "ntfs", "references_checked": count, "truncated": False}
    if spec["fat_copies"] == 2:
        for position in range(0, spec["fat_size"], 4096):
            size = min(4096, spec["fat_size"] - position)
            if session.read_at(spec["fat_offset"] + position, size) != \
                    session.read_at(spec["fat_offset"] + spec["fat_size"] + position, size):
                raise RaidError("FAT_COPY_MISMATCH")
    queue = [(fs.root, 0)]
    count = 0
    seen = set()
    while queue:
        parent, depth = queue.pop()
        if depth > 16:
            raise RaidError("FS_DIRECTORY_DEPTH_LIMIT")
        for child in parent.iterdir():
            if child.name in (".", ".."): continue
            count += 1
            if count > limit:
                return {"kind": "fat32", "references_checked": count - 1, "truncated": True}
            if child.is_directory():
                if child.cluster in seen:
                    raise RaidError("FAT_DIRECTORY_CYCLE")
                seen.add(child.cluster)
                queue.append((child, depth + 1))
            elif child.size:
                with child.open() as data:
                    if len(data.read(min(512, child.size))) != min(512, child.size):
                        raise RaidError("FAT_FILE_SHORT_READ")
    return {"kind": "fat32", "references_checked": count, "truncated": False}
