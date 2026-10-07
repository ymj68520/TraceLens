#!/usr/bin/env bash
# nbdkit
# Copyright (C) Red Hat Inc.
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
# * Neither the name of Red Hat nor the names of its contributors may be
# used to endorse or promote products derived from this software without
# specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY RED HAT AND CONTRIBUTORS ''AS IS'' AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
# PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL RED HAT OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
# USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
# OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
# SUCH DAMAGE.

source ./functions.sh
set -e
set -x
set -u

requires_plugin file
requires nbdsh
requires guestfish --version

sock=$(mktemp -u /tmp/nbdkit-test-sock.XXXXXX)
files="$sock ext2-parallel.pid ext2-parallel.out ext2-parallel.err \
ext2-parallel.img"
rm -f $files
cleanup_fn rm -f $files

# Create an image with two writable files
guestfish \
    sparse ext2-parallel.img 10M : \
    run : \
    mkfs ext4 /dev/sda : \
    mount /dev/sda / : \
    write /one hello : \
    write /two goodbye

# Set up a long-running server responsive to the client's export name
start_nbdkit -P ext2-parallel.pid -U $sock --filter=ext2 \
    file ext2-parallel.img ext2file=exportname

# Demonstrate 3 clients with parallel connections (but interleaved actions):
# first reads from /one,
# second writes to /one,
# third reads from /two
# second flushes
# first reads updated /one
export sock
nbdsh -c '
import os
sock = os.getenv("sock")

h1 = nbd.NBD()
h1.set_export_name("/one")
h1.connect_unix(sock)

h2 = nbd.NBD()
h2.set_export_name("/one")
h2.connect_unix(sock)

h3 = nbd.NBD()
h3.set_export_name("/two")
h3.connect_unix(sock)

buf1 = h1.pread(5, 0)
assert buf1 == b"hello"
h2.pwrite(b"world", 0)
buf3 = h3.pread(7, 0)
assert buf3 == b"goodbye"
h2.flush()

# Even with the flush, two handles visiting the same inodes do not share
# a cache.  A new handle sees the updated inode content...
h4 = nbd.NBD()
h4.set_export_name("/one")
h4.connect_unix(sock)
buf4 = h4.pread(5, 0)
assert buf4 == b"world"
# ...but the older handle still sees old data.
buf1 = h1.pread(5, 0)
assert buf1 == b"hello"

h1.shutdown()
h2.shutdown()
h3.shutdown()
h4.shutdown()
'
