# SPDX-License-Identifier: AGPL-3.0-or-later
"""Strict adaptation of pinned MIT ewfprobe; source and notice remain local.

Upstream pads short reads and records checksum errors. RAID inputs reject these
instead. Segment discovery is never implicit; format/location parsing is reused.
"""
import struct
import zlib

from . import vendor


def open_explicit(handles):
    from .core import RaidError
    ewf = vendor.load("qnxprobe", "ewfprobe")

    class StrictEwfImage(ewf.EwfImage):
        def _chunk(self, index):
            cached = self._cache.get(index)
            if cached is not None:
                self._cache.move_to_end(index)
                return cached
            segment, start, end, compressed = self._chunk_location(index)
            want = min(self.chunk_size, self.media_size - index * self.chunk_size)
            if not 0 < want <= 16 * 1024**2:
                raise RaidError("EWF_CHUNK_LIMIT_OR_INVALID")
            handle = self._handle(segment)
            handle.seek(start)
            if compressed:
                decoder = zlib.decompressobj()
                data = decoder.decompress(handle.read(max(0, end - start)), self.chunk_size + 1)
                if not decoder.eof or len(data) not in (want, self.chunk_size):
                    raise RaidError("EWF_SHORT_OR_OVERSIZED_COMPRESSED_CHUNK")
                data = data[:want]  # declared last-media chunk, not padded disk data
            else:
                data = handle.read(want)
                trailer = handle.read(4)
                if len(data) != want or len(trailer) != 4:
                    raise RaidError("EWF_SHORT_CHUNK")
                if zlib.adler32(data) & 0xffffffff != struct.unpack("<I", trailer)[0]:
                    raise RaidError("EWF_CHUNK_CHECKSUM_MISMATCH")
            self._cache[index] = data
            if len(self._cache) > ewf.CHUNK_CACHE:
                self._cache.popitem(last=False)
            return data

    files = [f"/proc/self/fd/{handle.fileno()}" for handle in handles]
    result = StrictEwfImage(files[0], segments=files)
    if not 0 < result.chunk_size <= 16 * 1024**2:
        result.close()
        raise RaidError("EWF_CHUNK_LIMIT_OR_INVALID")
    return result
