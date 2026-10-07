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

# Demonstrate a fix for a bug where blocksize overflowed 32 bits

source ./functions.sh
set -e
set -x
set -u

requires_run
requires_plugin eval
requires_nbdsh_uri
requires nbdsh --base-allocation --version

# Script a sparse server that requires 512-byte aligned requests.
exts='
if test $(( ($3|$4) & 511 )) != 0; then
  echo "EINVAL request unaligned" 2>&1
  exit 1
fi
echo 0 5G 0
'

# We also need an nbdsh script to parse all extents, coalescing adjacent
# types for simplicity.
# FIXME: Once nbdkit plugin version 3 allows 64-bit block extents, run
# this test twice, once for each bit size (32-bit needs 2 extents, 64-bit
# will get the same result with only 1 extent).
define script <<'EOF'
size = h.get_size()
offs = 0
entries = []
def f(metacontext, offset, e, err):
    global entries
    global offs
    assert offs == offset
    for length, flags in zip(*[iter(e)] * 2):
        if entries and flags == entries[-1][1]:
            entries[-1] = (entries[-1][0] + length, flags)
        else:
            entries.append((length, flags))
        offs = offs + length

# Test a loop over the entire device
while offs < size:
    len = min(size - offs, 2**32-1)
    h.block_status(len, offs, f)
assert entries == [(5 * 2**30, 0)]
EOF
export script

# Now run everything
nbdkit --filter=blocksize eval minblock=512 \
       get_size='echo 5G' pread='exit 1' extents="$exts" \
       --run 'nbdsh --base-allocation -u "$uri" -c "$script"'
