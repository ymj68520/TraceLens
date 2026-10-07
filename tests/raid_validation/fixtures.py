# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synthetic MD v1 fixtures, independent of the production parser/mapper.

Known logical bytes are the oracle. Encoding is independently defined from
Linux MD format/layout definitions, not read back from dissect to form expected.
No md device is created; no original evidence is used.
"""
from __future__ import annotations

from pathlib import Path
import struct
import uuid

CHUNK = 4096
OFFSET = 8192


def checksum(header: bytearray):
    struct.pack_into("<I", header, 216, 0)
    values = [int.from_bytes(header[i:i + 4], "little") for i in range(0, len(header), 4)]
    total = sum(values)
    struct.pack_into("<I", header, 216, ((total >> 32) + (total & 0xffffffff)) & 0xffffffff)


def make_members(root: Path, level=5, *, logical=None, layout=2, count=3,
                 metadata_sector=8, data_offset=OFFSET):
    root.mkdir(parents=True, exist_ok=True)
    if logical is None:
        # Every block differs; spans hundreds of stripes and cache alignments.
        logical = b"".join((f"known logical block {i:05d}: source-independent oracle\n".encode()
                              * 128)[:CHUNK].ljust(CHUNK, b"-") for i in range(192))
    width = count if level == 0 else count - 1 if level == 5 else 1
    size = ((len(logical) + CHUNK * width - 1) // (CHUNK * width)) * CHUNK * width
    expected = logical.ljust(size, b"\0")
    component = size // width
    payloads = [bytearray(component) for _ in range(count)]
    if level == 1:
        payloads = [bytearray(expected) for _ in range(count)]
    elif level == 0:
        for block in range(size // CHUNK):
            role, stripe = block % count, block // count
            payloads[role][stripe * CHUNK:(stripe + 1) * CHUNK] = expected[block * CHUNK:(block + 1) * CHUNK]
    elif level == 5:
        for stripe in range(component // CHUNK):
            parity_role = ((count - 1 - stripe % count) if layout in (0, 2) else
                           stripe % count if layout in (1, 3) else 0 if layout == 4 else count - 1)
            data_roles = ([(parity_role + 1 + i) % count for i in range(count - 1)]
                          if layout in (2, 3) else [r for r in range(count) if r != parity_role])
            parity = 0
            for i, role in enumerate(data_roles):
                logical_block = stripe * (count - 1) + i
                data = expected[logical_block * CHUNK:(logical_block + 1) * CHUNK]
                payloads[role][stripe * CHUNK:(stripe + 1) * CHUNK] = data
                parity ^= int.from_bytes(data, "little")
            payloads[parity_role][stripe * CHUNK:(stripe + 1) * CHUNK] = parity.to_bytes(CHUNK, "little")
    else:
        raise ValueError("fixture level unsupported")
    array_uuid = uuid.UUID("7647a151-dba1-452a-a21a-24df1dcfe9ad").bytes_le
    members = []
    for role, data in enumerate(payloads):
        header = bytearray(256 + count * 2)
        struct.pack_into("<II", header, 0, 0xa92b4efc, 1)
        header[16:32] = array_uuid
        header[32:64] = b"tracelens:synthetic".ljust(32, b"\0")
        struct.pack_into("<Q", header, 64, 1700000000)
        struct.pack_into("<iI", header, 72, level, layout if level != 1 else 0)
        struct.pack_into("<QII", header, 80, component // 512, CHUNK // 512, count)
        struct.pack_into("<QQQQ", header, 128, data_offset // 512, component // 512,
                         metadata_sector, (1 << 64) - 1)
        struct.pack_into("<I", header, 160, role)
        header[168:184] = uuid.UUID(int=role + 1).bytes_le
        struct.pack_into("<QQQ", header, 192, 1700000000, 7, (1 << 64) - 1)
        struct.pack_into("<I", header, 220, count)
        struct.pack_into("<" + "H" * count, header, 256, *range(count))
        checksum(header)
        name = f"成员 {chr(90 - role)}.raw"
        path = root / name
        with path.open("wb") as output:
            output.truncate(max(data_offset + len(data), metadata_sector * 512 + len(header)) + 8192)
            output.seek(metadata_sector * 512)
            output.write(header)
            output.seek(data_offset)
            output.write(data)
        members.append({"files": [name]})
    return list(reversed(members)), expected


def edit_metadata(path: Path, offset: int, fmt: str, value, *, repair_checksum=True):
    with path.open("r+b") as output:
        output.seek(4096)
        header = bytearray(output.read(256))
        count = struct.unpack_from("<I", header, 220)[0]
        header.extend(output.read(count * 2))
        struct.pack_into(fmt, header, offset, value)
        if repair_checksum:
            checksum(header)
        output.seek(4096)
        output.write(header)
