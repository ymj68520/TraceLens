# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reuse the pinned Dissect mapper, correcting only its stripe read length."""
from .core import RaidError


def bounded_raid5(virtual):
    from dissect.volume.raid.stream import RAID456Stream

    class BoundedRAID5Stream(RAID456Stream):
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

    return BoundedRAID5Stream(virtual)
