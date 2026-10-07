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

# Test evil filter in the default mode ("stuck-bits").

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
# Since 1 in 800,000 bits are stuck (on average), for every 100,000
# bytes that we read we expect about 1 stuck bit.  Note however that
# bits are stuck randomly low or high, and against the null filter you
# cannot see a stuck low bit, so in fact we expect to see only 1 stuck
# bit per 200,000 bytes.
#
# There is a separate test for stuck low bits (test-evil-stuck-low-bits.sh).
#
# Also stuck bits should be consistent across reads.

def count_bits(buf):
    r = 0
    for i in range(0, len(buf)-1):
        if buf[i] != 0:
            r += bin(buf[i]).count("1")
    return r

def find_bit(buf):
    for i in range(0, len(buf)-1):
        if buf[i] != 0:
            return i
    return 0

# Expect about 50 stuck-high bits.
buf = h.pread(10000000, 0)
bits = count_bits(buf)
print("stuck high bits: %d (expected 50)" % bits)
assert(bits > 20 and bits < 80)

# If we read subsets they should match the contents of the buffer.
i = find_bit(buf)
buf1 = h.pread(1000, i)
assert(buf1 == buf[i:i+1000])
EOF
export script

# Run nbdkit with the evil filter.
nbdkit --filter=evil --filter=noextents \
       null 1G evil-probability=1/800000 \
       --run ' nbdsh -u "$uri" -c "$script" '
