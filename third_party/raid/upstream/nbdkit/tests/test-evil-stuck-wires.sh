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

# Test evil filter in stuck-wires mode.

source ./functions.sh
set -e
set -x
set -u

requires_plugin null
requires_filter evil
requires_filter noextents
requires_nbdsh_uri
requires_run

define script <<'EOF'
# Reads from the filter should have 1:10,000 bits stuck high or low.
# However we don't see stuck low bits since we are always reading
# zeroes, so we only expect about 1:20,000 bits stuck high.
#
# If we read 10,000,000 bytes (80,000,000 bits) we would expect about
# 4000 stuck bits.
#
# No matter where we read from the pattern of stuck bits should be the
# same (stuck wires, not backing bits).

def count_bits(buf):
    r = 0
    for i in range(0, len(buf)-1):
        if buf[i] != 0:
            r += bin(buf[i]).count("1")
    return r

buf1 = h.pread(10000000, 0)
bits = count_bits(buf1)
print("stuck high bits: %d (expected 4000)" % bits)
assert(bits > 3000 and bits < 5000)

# These buffers should be identical.
buf2 = h.pread(10000000, 1024)
buf3 = h.pread(10000000, 32*1024*1024 - 9999)
assert(buf1 == buf2)
assert(buf1 == buf3)
EOF
export script

# Run nbdkit with the evil filter.
nbdkit --filter=evil --filter=noextents \
       null 1G evil=stuck-wires evil-probability=1/10000 \
       --run ' nbdsh -u "$uri" -c "$script" '
