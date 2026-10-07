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

# Test the pattern plugin.

source ./functions.sh
set -e
set -x
set -u

requires_run
requires_nbdsh_uri

define script <<'EOF'
# Generate the expected pattern in the given range.
# This only works for 8-byte aligned ranges.
def generated_expected(start, end):
    assert start % 8 == 0
    assert end % 8 == 0
    expected = bytearray()
    for i in range(start, end, 8):
        expected = expected + i.to_bytes(8, 'big')
    return expected

# Check actual == expected, with printing
def check_same(actual, expected):
    if actual == expected:
        print("check_same: passed", flush=True)
    else:
        print("actual   = %r" % actual, flush=True)
        print("expected = %r" % expected, flush=True)
        assert False

# Read an aligned range at the beginning of the disk.
expected = generated_expected(0, 64)
actual = h.pread(64, 0)
check_same(actual, expected)

# Read starting from an unaligned offset.
actual = h.pread(60, 4)
check_same(actual, expected[4:])

# Read ending at an unaligned offset.
actual = h.pread(60, 0)
check_same(actual, expected[:60])

# Same as above, but around offset 1,000,000.
expected = generated_expected(1000000, 1000000+64)
actual = h.pread(64, 1000000)
check_same(actual, expected)
actual = h.pread(61, 1000003)
check_same(actual, expected[3:])
actual = h.pread(60, 1000000)
check_same(actual, expected[:60])

# Same as above, but around offset 2G.
offset = 2*1024*1024*1024 - 32
expected = generated_expected(offset, offset+64)
actual = h.pread(64, offset)
check_same(actual, expected)
actual = h.pread(59, offset+5)
check_same(actual, expected[5:])
actual = h.pread(60, offset)
check_same(actual, expected[:60])

# Same as above, but around offset 4G.
offset = 4*1024*1024*1024 - 32
expected = generated_expected(offset, offset+64)
actual = h.pread(64, offset)
check_same(actual, expected)
actual = h.pread(59, offset+5)
check_same(actual, expected[5:])
actual = h.pread(63, offset)
check_same(actual, expected[:63])

# Finish at the end of the disk.
offset = 5*1024*1024*1024 - 64
expected = generated_expected(offset, offset+64)
actual = h.pread(64, offset)
check_same(actual, expected)
EOF
export script

# Run nbdkit-pattern-plugin.
# Use a disk > 4G so we can test 2G and 4G boundaries.
nbdkit pattern 5G --run ' nbdsh -u "$uri" -c "$script" '
