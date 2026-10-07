# -*- python -*-
# nbdkit
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

# This fake google-cloud-storage module is used to test the gcs plugin.  See
# also tests/test-gcs.sh

import nbdkit


nbdkit.debug("loaded mocked google.cloud.storage module for tests")

buf = b'x'*4096 + b'y'*2048 + b'z'*2048


class Client(object):
    def __init__(self):
        pass

    @staticmethod
    def from_service_account_json(json_credentials_path: str):
        return Client()

    def bucket(self, bucket_name: str):
        return Bucket(self, bucket_name)


class Bucket(object):
    def __init__(self, client: Client, name):
        self.client = client
        self.name = name

    def get_blob(self, key: str):
        return Blob(self, key)

    def blob(self, key: str):
        return Blob(self, key)


class Blob(object):
    def __init__(self, bucket: Bucket, key: str):
        self.bucket = bucket
        self.key = key
        self.size = len(buf)

    def download_as_bytes(self, start: int, end: int, raw_download=True,
                          checksum=None):
        if start is None and end is None:
            b = buf
        elif start is None and end is not None:
            b = buf[:end + 1]
        elif start is not None and end is None:
            b = buf[start:]
        else:
            b = buf[start:end + 1]

        return b
