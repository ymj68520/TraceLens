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

requires_plugin ones
requires_filter evil
requires_nbdsh_uri
requires_run

define script <<'EOF'
# See description in test-evil-stuck-high-bits.sh.  This test uses the
# ones plugin to test for stuck low bits.  The other parameters are
# the same.

def count_bits(buf):
    r = 0
    for i in range(0, len(buf)-1):
        if buf[i] != 0xff:
            r += 8 - bin(buf[i]).count("1")
    return r

def find_bit(buf):
    for i in range(0, len(buf)-1):
        if buf[i] != 0xff:
            return i
    return 0

# Expect about 50 stuck-low bits.
buf = h.pread(10000000, 32*1024*1024)
bits = count_bits(buf)
print("stuck low bits: %d (expected 50)" % bits)
assert(bits > 20 and bits < 80)

# If we read subsets they should match the contents of the buffer.
i = find_bit(buf)
buf1 = h.pread(1000, 32*1024*1024 + i)
assert(buf1 == buf[i:i+1000])
EOF
export script

# Run nbdkit with the evil filter.
nbdkit --filter=evil \
       ones 1G evil-probability=1/800000 \
       --run ' nbdsh -u "$uri" -c "$script" '
