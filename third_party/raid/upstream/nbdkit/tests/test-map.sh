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

# Simple tests of the map filter.

source ./functions.sh
set -e
set -x
set -u

requires_run
requires_plugin pattern
requires_nbdsh_uri

define script <<'EOF'
import random

# 0-511 and 512-1023 are mapped to the same data (at 0-511).
b1 = h.pread(512, 0)
b2 = h.pread(512, 512)
assert b1 == b2
assert b1[0:8] == b'\x00\x00\x00\x00\x00\x00\x00\x00'
assert b1[8:16] == b'\x00\x00\x00\x00\x00\x00\x00\x08'
assert b1[504:512] == b'\x00\x00\x00\x00\x00\x00\x01\xf8'

# 2**63-512 through to 2**63-1 (511 bytes) is mapped to 0.
b1 = h.pread(511, 0)
b2 = h.pread(511, 2**63-512)
assert b1 == b2
assert b1[0:8] == b'\x00\x00\x00\x00\x00\x00\x00\x00'
assert b1[8:16] == b'\x00\x00\x00\x00\x00\x00\x00\x08'
assert b1[504:511] == b'\x00\x00\x00\x00\x00\x00\x01'

# Other parts of the disk are 1-1 mapped.
offset = random.randint(1024, 2**63-1024) & ~7
len = random.randint(1, 64) * 8
b = h.pread(len, offset)
for i in range(0, len, 8):
    actual = b[i:i+8]
    expected = (offset + i).to_bytes(8, 'big')
    print("%r %r" % (actual, expected))
    assert actual == expected
EOF
export script

# 9223372036854775296 == 2**63-512, so the last (partial) sector is also
# mapped.
# Note the rule that the first map on the command line has precedence.
define map <<'EOF'
--filter=map
map=512-1023:0
map=512-1023:50000
map=9223372036854775296-9223372036854775807:0
EOF

# Run the test.
nbdkit pattern $largest_disk $map --run ' nbdsh -u "$uri" -c "$script" '
