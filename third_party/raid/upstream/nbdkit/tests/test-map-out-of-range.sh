#!/usr/bin/env bash
# nbdkit
# Copyright Red Hat
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

# Test how the filter behaves when used to map I/O out of range.

source ./functions.sh
set -e
set -x
set -u

requires_run
requires_nbdsh_uri

# In this map, sector 0 is mapped completely beyond the end
# of the disk.  Sector 1 is mapped so that only the last byte
# is beyond the end of the disk.
define map <<'EOF'
--filter=map
map=0-511:1048576
map=512-1023:1048065
EOF

define script <<'EOF'
# Reading any part of sector 0 is expected to return EIO.
try:
    b = h.pread(512, 0);
    assert False  # not reached
except nbd.Error as ex:
    assert ex.errno == "EIO"
try:
    h.pread(1, 0);
    assert False  # not reached
except nbd.Error as ex:
    assert ex.errno == "EIO"
try:
    h.pread(1, 511);
    assert False  # not reached
except nbd.Error as ex:
    assert ex.errno == "EIO"

# Reading the first 511 bytes of sector 1 should be fine.
h.pread(511, 512);

# Reading the last byte of sector 1 is expected to return EIO.
try:
    h.pread(1, 1023)
    assert False  # not reached
except nbd.Error as ex:
    assert ex.errno == "EIO"
try:
    h.pread(512, 512)
    assert False  # not reached
except nbd.Error as ex:
    assert ex.errno == "EIO"

# Any other read should be fine.
h.pread(2048, 2048)
h.pread(100, 100000)
EOF
export script

# Run the test.
nbdkit null 1M $map --run ' nbdsh -u "$uri" -c "$script" '
