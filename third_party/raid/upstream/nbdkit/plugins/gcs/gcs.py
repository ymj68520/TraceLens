#!@sbindir@/nbdkit python
# -*- python -*-
# Copyright Infrascale Inc.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# * Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# * Neither the name of Infrascale nor the names of its contributors may be
# used to endorse or promote products derived from this software without
# specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY INFRASCALE AND CONTRIBUTORS ''AS IS'' AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
# PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL INFRASCALE OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
# USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
# OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
# SUCH DAMAGE.

import base64
import errno
import os
import secrets
import tempfile
import threading
import unittest
from contextlib import contextmanager
from typing import Optional, Union, List
from unittest.mock import patch

import nbdkit

from google.api_core.exceptions import NotFound, GatewayTimeout, \
    DeadlineExceeded
from google.cloud import storage as gcs


nbdkit.debug("gcs: imported google.cloud.storage from %s" % gcs.__file__)

API_VERSION = 2
BinaryData = Union[bytes, bytearray, memoryview]


class Config:
    """Holds configuration data passed in by the user."""

    def __init__(self) -> None:
        self.json_creds = None
        self.bucket_name = None
        self.key_name = None
        self.dev_size = None
        self.obj_size = None

    def set(self, key: str, value: str) -> None:
        """Set a configuration value."""

        if key == "json-credentials" or key == "json_credentials":
            self.json_creds = value
        elif key == "bucket":
            self.bucket_name = value
        elif key == "key":
            self.key_name = value
        elif key == 'size':
            self.dev_size = nbdkit.parse_size(value)
        elif key == 'object-size' or key == "object_size":
            self.obj_size = nbdkit.parse_size(value)
        else:
            raise RuntimeError("unknown parameter %s" % key)

    def validate(self) -> None:
        """Validate configuration settings."""

        if self.bucket_name is None:
            raise RuntimeError("bucket parameter missing")
        if self.key_name is None:
            raise RuntimeError("key parameter missing")

        if (self.dev_size and not self.obj_size or
                self.obj_size and not self.dev_size):
            raise RuntimeError(
                "`size` and `object-size` parameters must always be "
                "specified together")

        if self.dev_size and self.dev_size % self.obj_size != 0:
            raise RuntimeError('`size` must be a multiple of `object-size`')


def thread_model():
    return nbdkit.THREAD_MODEL_PARALLEL


def can_write(server):
    return cfg.obj_size is not None


def can_multi_conn(server):
    return True


def can_trim(server):
    return True


def can_zero(server):
    return True


def can_fast_zero(server):
    return True


def can_cache(server):
    return nbdkit.CACHE_NONE


def block_size(server):
    if not cfg.obj_size:
        # More or less arbitrary.
        return (1, 512 * 1024, 0xffffffff)

    # Should return (minimum, preferred, maximum) block size. We return the
    # same value for preferred and maximum because even though the plugin can
    # handle arbitrary large and small blocks, the performance penalty is
    # huge, and it is always preferable for the client to split up requests
    # as needed. At the same time, the minimum accessible block size is still
    # 1 byte.
    return (1, cfg.obj_size, cfg.obj_size)


def can_fua(server):
    return nbdkit.FUA_NATIVE


def can_flush(server):
    return True


def config(key, value):
    cfg.set(key, value)


def config_complete():
    cfg.validate()


def open(readonly):
    return Server()


def get_size(server):
    return server.get_size()


def pread(server, buf, offset, flags):
    try:
        return server.pread(buf, offset, flags)
    except (GatewayTimeout, DeadlineExceeded):
        nbdkit.debug('GCS connection timed out on pread()')
        nbdkit.set_error(errno.ETIMEDOUT)


def pwrite(server, buf, offset, flags):
    try:
        return server.pwrite(buf, offset, flags)
    except (GatewayTimeout, DeadlineExceeded):
        nbdkit.debug('GCS connection timed out on write()')
        nbdkit.set_error(errno.ETIMEDOUT)


def trim(server, size, offset, flags):
    try:
        return server.trim(size, offset, flags)
    except (GatewayTimeout, DeadlineExceeded):
        nbdkit.debug('GCS connection timed out on trim()')
        nbdkit.set_error(errno.ETIMEDOUT)


def zero(server, size, offset, flags):
    try:
        return server.zero(size, offset, flags)
    except (GatewayTimeout, DeadlineExceeded):
        nbdkit.debug('GCS connection timed out on trim()')
        nbdkit.set_error(errno.ETIMEDOUT)


def flush(server, flags):
    # Flush is implicitly done on every request.
    return


class Server:
    """Handles NBD requests for one connection."""

    def __init__(self) -> None:
        if cfg.json_creds is None:
            nbdkit.debug(
                'Init GCS client using Application Default Credentials')
            self.gcs = gcs.Client()
        else:
            self.gcs = gcs.Client.from_service_account_json(cfg.json_creds)

        self.bucket = self.gcs.bucket(cfg.bucket_name)

    def get_size(self) -> int:
        if cfg.dev_size:
            return cfg.dev_size

        blob = self.bucket.get_blob(cfg.key_name)
        return 0 if blob is None else blob.size

    def pread(self, buf: Union[bytearray, memoryview],
              offset: int, flags: int) -> None:
        to_read = len(buf)
        if not cfg.obj_size:
            buf[:] = self._get_object(cfg.key_name, size=to_read, off=offset)
            return

        read = 0

        (blockno, block_offset) = divmod(offset, cfg.obj_size)
        while to_read > 0:
            key = f"{cfg.key_name}/{blockno:016x}"
            len_ = min(to_read, cfg.obj_size - block_offset)
            buf[read:read + len_] = self._get_object(
                key, size=len_, off=block_offset
            )
            to_read -= len_
            read += len_
            blockno += 1
            block_offset = 0

    def _get_object(self, obj_name: str, size: int, off: int) -> bytes:
        """Read *size* bytes from *obj_name*, starting at *off*."""

        try:
            blob = self.bucket.blob(obj_name)
            buf = blob.download_as_bytes(start=off, end=off + size - 1,
                                         checksum=None, raw_download=True)
        except NotFound:
            return bytearray(size)

        assert len(buf) == size, f'requested {size} bytes, got {len(buf)}'
        return buf

    def pwrite(self, buf: BinaryData, offset: int, flags: int) -> None:
        # We can ignore FUA flags, because every write is always flushed

        if not cfg.obj_size:
            raise RuntimeError('Unable to write in single-object mode')

        # memoryviews can be sliced without copying the data
        if not isinstance(buf, memoryview):
            buf = memoryview(buf)

        # Calculate block number and offset within the block for the
        # first byte that we need to write.
        (blockno1, block_offset1) = divmod(offset, cfg.obj_size)

        # Calculate block number of the last block that we have to
        # write to, and how many bytes we need to write into it.
        (blockno2, block_len2) = divmod(offset + len(buf), cfg.obj_size)

        # Special case: start and end is within the same one block
        if blockno1 == blockno2 and (block_offset1 != 0 or block_len2 != 0):
            nbdkit.debug(f"pwrite(): write at offset {offset} not aligned, "
                         f"covers bytes {block_offset1} to {block_len2} of "
                         f"block {blockno1}. Rewriting full block...")

            # We could separately fetch the prefix and suffix, but give that
            # we're always writing full blocks, it's likely that the latency of
            # two separate read requests would be much bigger than the savings
            # in volume.
            key = f'{cfg.key_name}/{blockno1:016x}'
            with obj_lock(key):
                fbuf = bytearray(self._get_object(
                    key, size=cfg.obj_size, off=0))
                fbuf[block_offset1:block_len2] = buf
                self._put_object(key, fbuf)
                return

        # First write is not aligned to first block
        if block_offset1:
            nbdkit.debug(
                f"pwrite(): write at offset {offset} not aligned, "
                f"starts {block_offset1} bytes into block {blockno1}. "
                "Rewriting full block...")
            key = f'{cfg.key_name}/{blockno1:016x}'
            with obj_lock(key):
                pre = self._get_object(key, size=block_offset1, off=0)
                len_ = cfg.obj_size - block_offset1
                self._put_object(key, pre + buf[:len_])
                buf = buf[len_:]
                blockno1 += 1

        # Last write is not a full block
        if block_len2:
            nbdkit.debug(f"pwrite(): write at offset {offset} not aligned, "
                         f"ends {cfg.obj_size - block_len2} bytes before "
                         f"block {blockno2 + 1}. Rewriting full block...")
            key = f'{cfg.key_name}/{blockno2:016x}'
            with obj_lock(key):
                len_ = cfg.obj_size - block_len2
                post = self._get_object(key, size=len_, off=block_len2)
                self._put_object(key, self._concat(buf[-block_len2:], post))
                buf = buf[:-block_len2]

        off = 0
        for blockno in range(blockno1, blockno2):
            key = f"{cfg.key_name}/{blockno:016x}"
            with obj_lock(key):
                nbdkit.debug(f"pwrite(): writing block {blockno}...")
                self._put_object(key, buf[off:off + cfg.obj_size])
                off += cfg.obj_size

    def _put_object(self, obj_name: str, buf: BinaryData) -> None:
        """Write *buf* into *obj_name"""

        assert len(buf) == cfg.obj_size

        # GCS library does not support reading from memoryviews :-(
        if isinstance(buf, memoryview):
            buf = buf.tobytes()
        elif isinstance(buf, bytearray):
            buf = bytes(buf)

        blob = self.bucket.blob(obj_name)
        blob.upload_from_string(buf, content_type='application/octet-stream')

    def zero(self, size: int, offset: int, flags: int) -> None:
        nbdkit.debug(f'Processing zero(size={size}, off={offset})')
        if size == 0:
            return

        # Calculate block number and offset within the block for the
        # first byte that we need to write.
        (blockno1, block_offset1) = divmod(offset, cfg.obj_size)

        # Calculate block number of the last block that we have to
        # write to, and how many bytes we need to write into it.
        (blockno2, block_len2) = divmod(offset + size, cfg.obj_size)

        if blockno1 == blockno2:
            nbdkit.debug(f'Zeroing {size} bytes in block {blockno1} '
                         f'(offset {offset})')
            self.pwrite(bytearray(size), offset=offset, flags=0)
            return

        if block_offset1:
            len_ = cfg.obj_size - block_offset1
            nbdkit.debug(f'Zeroing last {len_} bytes of block {blockno1} '
                         f'(offset {offset})')
            self.pwrite(bytearray(len_), offset=offset, flags=0)
            blockno1 += 1

        if block_len2:
            off = cfg.obj_size * blockno2
            nbdkit.debug(f'Zeroing first {block_len2 - 1} bytes of block '
                         f'{blockno2} (offset {off})')
            self.pwrite(bytearray(block_len2), offset=off, flags=0)

        self._delete_objects(blockno1, blockno2)

    def trim(self, size: int, offset: int, flags: int) -> None:
        nbdkit.debug(f'Processing trim(size={size}, off={offset})')
        if size == 0:
            return

        # Note, NBD protocol allows to round the offset up and size down to
        # meet internal alignment constraints.

        # Calculate block number and offset within the block for the
        # first byte that we need to trim.
        (blockno1, block_offset1) = divmod(offset, cfg.obj_size)
        if block_offset1 != 0:
            blockno1 += 1

        # Calculate block number of the block following the last one that we
        # have to trim fully.
        (blockno2, _) = divmod(offset + size, cfg.obj_size)

        if blockno1 == blockno2:
            nbdkit.debug('nothing to delete')
            return

        self._delete_objects(blockno1, blockno2)

    @staticmethod
    def _delete_object_callback(obj: str) -> None:
        """ Called by the library on attempt to delete non-existent object """
        # Simply ignore callback

    def _delete_objects(self, first: int, last: int) -> None:
        """Delete objects *first* (inclusive) to *last* (exclusive)"""
        nbdkit.debug(
            f'Deleting objects {first} (inclusive) to {last} (exclusive)...')

        if first >= last:
            return

        first_key = f"{cfg.key_name}/{first:016x}"
        end_key = f"{cfg.key_name}/{last:016x}"

        to_delete = []
        keys = self._list_objects(f"{cfg.key_name}/", first_key, end_key)
        for key in keys:
            if key >= end_key:
                break

            to_delete.append(key)
            nbdkit.debug(f'Marking object {key} for removal')
            if len(to_delete) >= 1000:
                self.bucket.delete_blobs(to_delete,
                                         on_error=self._delete_object_callback)

                del to_delete[:]

        if to_delete:
            self.bucket.delete_blobs(to_delete,
                                     on_error=self._delete_object_callback)

    def _list_objects(self, prefix: str,
                      first_offset: Optional[str] = None,
                      end_offset: Optional[str] = None) -> List[str]:
        """Return keys for objects in bucket.

        Lists all keys starting with *prefix* in lexicographic order, starting
        with the key following *first_offset* (inclusive) and ending with
        *end_offset* (exclusive).
        """

        blobs = self.bucket.list_blobs(prefix=prefix,
                                       fields="items(name),nextPageToken",
                                       start_offset=first_offset,
                                       end_offset=end_offset)
        for blob in blobs:
            yield blob.name

    @staticmethod
    def _concat(b1, b2):
        """Concatenate two byte-like objects (including memoryviews)"""

        l1 = len(b1)
        l3 = l1 + len(b2)
        b3 = bytearray(l3)
        b3[:l1] = b1
        b3[l1:] = b2

        return b3


class MultiLock:
    """Provides locking for large amounts of entities.

    This class provides locking for a dynamically changing and potentially
    large set of entities, avoiding the need to allocate a separate lock for
    each entity. The `acquire` and `release` methods have an additional
    argument, the locking key, and only locks with the same key can see each
    other (ie, several threads can hold locks with different locking keys at
    the same time).
    """

    def __init__(self):
        self.locked_keys = set()
        self.cond = threading.Condition()

    @contextmanager
    def __call__(self, key):
        self.acquire(key)
        try:
            yield
        finally:
            self.release(key)

    def acquire(self, key):
        """Acquire lock for given key."""

        with self.cond:
            while key in self.locked_keys:
                self.cond.wait()

            self.locked_keys.add(key)

    def release(self, key):
        """Release lock on given key"""

        with self.cond:
            self.locked_keys.remove(key)
            self.cond.notify_all()


###################
# Global state    #
###################
cfg = Config()
obj_lock = MultiLock()


######################
# Unit Tests         #
######################

class BlobWithName:
    def __init__(self, name: str):
        self.name = name


class MockGcsClient:
    def __init__(self):
        self.keys = {}

    def bucket(self, bucket_name: str):
        return MockGcsBucket(self, bucket_name)

    def put_object(self, bucket: str, key: str, content):
        self.keys[(bucket, key)] = bytes(content)

    def get_object(self, bucket: str, key: str, start: int, end: int):
        our_key = (bucket, key)
        if our_key not in self.keys:
            raise NotFound(key)

        if start is not None and end is not None:
            buf = self.keys[our_key][start:end + 1]
        else:
            buf = self.keys[our_key]
        return buf

    def delete_objects(self, bucket: str, blobs, on_error):
        for el in blobs:
            key = (bucket, el)
            if key not in self.keys:
                on_error(el)
            del self.keys[key]

    def list_objects(self, bucket: str, prefix: str,
                     start_offset: Optional[str] = None,
                     end_offset: Optional[str] = None):
        all_keys = sorted(x[1] for x in self.keys
                          if x[0] == bucket and x[1].startswith(prefix))
        obj_list = []
        for k in all_keys:
            if start_offset is not None and k < start_offset:
                continue
            if end_offset is not None and k >= end_offset:
                continue
            obj_list.append(BlobWithName(k))

        return obj_list


class MockGcsBucket:
    def __init__(self, client: MockGcsClient, bucket_name: str):
        self.client = client
        self.bucket_name = bucket_name

    def blob(self, obj_name: str):
        return MockGcsBlob(self, obj_name)

    def list_blobs(self, prefix: str, fields: str,
                   start_offset: Optional[str] = None,
                   end_offset: Optional[str] = None):
        return self.client.list_objects(self.bucket_name, prefix,
                                        start_offset, end_offset)

    def delete_blobs(self, blobs, on_error):
        self.client.delete_objects(self.bucket_name, blobs, on_error)


class MockGcsBlob:
    def __init__(self, bucket: MockGcsBucket, blob_name: str):
        self.bucket = bucket
        self.blob_name = blob_name

    def upload_from_string(self, data, content_type: str):
        self.bucket.client.put_object(self.bucket.bucket_name,
                                      self.blob_name, data)

    def download_as_bytes(self, start: int, end: int, raw_download=True,
                          checksum=None):
        return self.bucket.client.get_object(self.bucket.bucket_name,
                                             self.blob_name, start, end)


class LocalTest(unittest.TestCase):
    def setUp(self):
        super().setUp()

        self.obj_size = 16
        self.dev_size = 20 * self.obj_size
        self.ref_fh = tempfile.TemporaryFile()
        self.ref_fh.truncate(cfg.dev_size)

        config('bucket', 'testbucket')
        config('key', 'nbdkit_test')
        config('object-size', str(self.obj_size))
        config('size', str(self.dev_size))

        config_complete()
        with patch.object(gcs, 'Client') as mock_client:
            mock_client.return_value = MockGcsClient()
            self.gcs = open(False)

    def tearDown(self) -> None:
        super().tearDown()
        self.ref_fh.close()

    @staticmethod
    def get_data(len):
        buf = secrets.token_bytes(len // 2 + 1)
        return base64.b16encode(buf)[:len]

    def compare_to_ref(self):
        fh = self.ref_fh
        bl = self.obj_size
        buf = bytearray(bl)
        fh.seek(0)
        for off in range(0, self.dev_size, bl):
            ref = fh.read(bl)
            pread(self.gcs, buf, off, flags=0)
            self.assertEqual(
                ref, buf, f'mismatch at off={off} (blk {off // bl})')

    def test_write_memoryview(self):
        buf = memoryview(bytearray(cfg.obj_size))
        pwrite(self.gcs, buf, 0, 0)
        pwrite(self.gcs, buf[10:], 42, 0)

    def test_read(self):
        fh = self.ref_fh
        bl = self.obj_size

        # Fill disk
        fh.seek(0)
        for off in range(0, self.dev_size, self.obj_size):
            buf = self.get_data(bl)
            pwrite(self.gcs, buf, offset=off, flags=0)
            fh.write(buf)
        self.compare_to_ref()

        # Test different kinds of read requests
        corner_cases = (
            1, 2,
            bl - 2, bl - 1, bl + 2,
            2 * bl - 1, 2 * bl, 2 * bl + 1,
            5 * bl - 5, 5 * bl, 5 * bl + 5)
        for off in (0,) + corner_cases:
            for len_ in corner_cases:
                buf = bytearray(len_)
                pread(self.gcs, buf, off, flags=0)
                fh.seek(off)
                ref = fh.read(len_)
                self.assertEqual(buf, ref)

    def test_write(self):
        fh = self.ref_fh
        bl = self.obj_size

        # Fill disk
        fh.seek(0)
        for off in range(0, self.dev_size, bl):
            buf = self.get_data(bl)
            pwrite(self.gcs, buf, offset=off, flags=0)
            fh.write(buf)
        self.compare_to_ref()

        # Test different kinds of write requests
        corner_cases = (
            1, 2,
            bl - 2, bl - 1, bl + 2,
            2 * bl - 1, 2 * bl, 2 * bl + 1,
            5 * bl - 5, 5 * bl, 5 * bl + 5)
        for off in (0,) + corner_cases:
            for len_ in corner_cases:
                buf = self.get_data(len_)
                pwrite(self.gcs, buf, off, flags=0)
                fh.seek(off)
                fh.write(buf)
                self.compare_to_ref()

    def test_zero(self):
        fh = self.ref_fh
        bl = self.obj_size

        # Fill disk
        fh.seek(0)
        for off in range(0, self.dev_size, bl):
            buf = self.get_data(bl)
            pwrite(self.gcs, buf, offset=off, flags=0)
            fh.write(buf)
        self.compare_to_ref()

        # Test different kinds of zero requests
        corner_cases = (
            1, 2,
            bl - 2, bl - 1, bl, bl + 2,
            2 * bl - 1, 2 * bl, 2 * bl + 1,
            5 * bl - 5, 5 * bl, 5 * bl + 5)
        for flags in (0, nbdkit.FLAG_MAY_TRIM):
            for off in (0,) + corner_cases:
                for len_ in corner_cases:
                    zero(self.gcs, len_, off, flags=flags)
                    fh.seek(off)
                    fh.write(bytearray(len_))
                    self.compare_to_ref()

                    # Re-fill with data
                    buf = self.get_data(len_)
                    pwrite(self.gcs, buf, off, flags=0)
                    fh.seek(off)
                    fh.write(buf)

    def test_trim(self):
        bl = self.obj_size

        # Fill disk
        for off in range(0, self.dev_size, self.obj_size):
            pwrite(self.gcs, self.get_data(bl), offset=off, flags=0)

        # Test different kinds of trim requests
        corner_cases = (
            1, 2,
            bl - 2, bl - 1, bl + 2,
            2 * bl - 1, 2 * bl, 2 * bl + 1,
            5 * bl - 5, 5 * bl, 5 * bl + 5)
        for off in (0,) + corner_cases:
            for len_ in corner_cases:
                (b1, o1) = divmod(off, bl)
                (b2, o2) = divmod(off + len_, bl)

                obj_count1 = len(list(self.gcs._list_objects(cfg.key_name)))
                trim(self.gcs, len_, off, flags=0)
                obj_count2 = len(list(self.gcs._list_objects(cfg.key_name)))

                blocks_to_delete = b2 - b1
                if o1 != 0 and blocks_to_delete >= 1:
                    blocks_to_delete -= 1

                self.assertEqual(obj_count1 - blocks_to_delete, obj_count2)

                # Re-fill with data
                pwrite(self.gcs, self.get_data(len_), off, flags=0)


# To run unit tests against a real GCS bucket, set the TEST_BUCKET and
# TEST_JSON_CREDENTIALS environment variables. The point of these tests is
# to make sure we're calling GCS correctly, not to test any plugin code.
@unittest.skipIf('TEST_BUCKET' not in os.environ,
                 'TEST_BUCKET environment variable not defined.')
@unittest.skipIf('TEST_JSON_CREDENTIALS' not in os.environ,
                 'TEST_JSON_CREDENTIALS environment variable not '
                 'defined.')
class RemoteTest(unittest.TestCase):
    def setUp(self):
        super().setUp()

        self.obj_size = 64
        self.dev_size = 20 * self.obj_size

        config('bucket', os.environ['TEST_BUCKET'])
        config('json-credentials', os.environ['TEST_JSON_CREDENTIALS'])
        config('key', 'nbdkit_test')
        config('object-size', str(self.obj_size))
        config('size', str(self.dev_size))

        config_complete()
        self.gcs = open(False)

    def tearDown(self) -> None:
        super().tearDown()

    @staticmethod
    def get_data(len):
        buf = secrets.token_bytes(len // 2 + 1)
        return base64.b16encode(buf)[:len]

    def test_zero(self):
        bs = self.obj_size
        ref_buf = bytearray(self.get_data(3 * bs))
        pwrite(self.gcs, ref_buf, 0, 0)

        zero_start = bs // 2
        zero(self.gcs, 2 * bs, zero_start, 0)
        ref_buf[zero_start:zero_start + 2 * bs] = bytearray(2 * bs)

        buf = bytearray(len(ref_buf))
        pread(self.gcs, buf, 0, 0)
        self.assertEqual(buf, ref_buf)

    def test_trim(self):
        ref_buf = bytearray(self.get_data(3 * self.obj_size))
        pwrite(self.gcs, ref_buf, 0, 0)

        obj_count1 = len(list(self.gcs._list_objects(cfg.key_name)))

        trim_start = self.obj_size // 2
        trim(self.gcs, 2 * self.obj_size, trim_start, 0)

        obj_count2 = len(list(self.gcs._list_objects(cfg.key_name)))
        self.assertEqual(obj_count1 - 1, obj_count2)

    def test_readwrite(self):
        ref_buf = self.get_data(2 * self.obj_size)
        start_off = self.obj_size // 2
        pwrite(self.gcs, ref_buf, start_off, 0)
        buf = bytearray(len(ref_buf))
        pread(self.gcs, buf, start_off, 0)
        self.assertEqual(buf, ref_buf)
