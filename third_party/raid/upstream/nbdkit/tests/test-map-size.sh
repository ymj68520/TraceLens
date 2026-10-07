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

# Test map-size parameter.

source ./functions.sh
set -e
set -x
set -u

requires_run
requires_plugin pattern
requires_nbdsh_uri

# Set the plugin size to 2 sectors and the map size to 4 sectors.
# Map sector 2 -> 0.
# Sector 3 is unmapped and should return EIO.
define map <<'EOF'
size=1024
map-size=2048
--filter=map
map=1024-1535:0
EOF

define script <<'EOF'
# Apparent size should be 4 sectors.
assert h.get_size() == 2048

# Sectors 0 and 1 should be 1-1 mapped.
b = h.pread(1024, 0)
assert b[0:8] == b'\x00\x00\x00\x00\x00\x00\x00\x00'
assert b[8:16] == b'\x00\x00\x00\x00\x00\x00\x00\x08'
assert b[504:512] == b'\x00\x00\x00\x00\x00\x00\x01\xf8'
assert b[1016:1024] == b'\x00\x00\x00\x00\x00\x00\x03\xf8'

# Sector 3 should be mapped to sector 0.
b = h.pread(512, 1024)
assert b[0:8] == b'\x00\x00\x00\x00\x00\x00\x00\x00'
assert b[8:16] == b'\x00\x00\x00\x00\x00\x00\x00\x08'
assert b[504:512] == b'\x00\x00\x00\x00\x00\x00\x01\xf8'

# Sector 4 should return EIO.
try:
    b = h.pread(512, 1536);
    assert False  # not reached
except nbd.Error as ex:
    assert ex.errno == "EIO"
EOF
export script

# Run the test.
nbdkit pattern $map --run ' nbdsh -u "$uri" -c "$script" '
