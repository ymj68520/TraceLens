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

# Test evil filter with cosmic rays.

source ./functions.sh
set -e
set -x
set -u

requires_run
requires_plugin null
requires_filter evil
requires_filter noextents
requires_nbdcopy
requires $PYTHON --version

f="test-evil-cosmic.out"
rm -f $f
cleanup_fn rm -f $f

# 80 million zero bits in the backing disk, and the filter will
# randomly flip (ie. set high) 1 in 800,000 bits, or about 100.

# XXX Actually the number of set bits clusters around 80.  There could
# be a mistake in my calculations or the interval algorithm we use
# might be biased.

export f
nbdkit null 10000000 \
       --filter=evil --filter=noextents \
       evil=cosmic-rays evil-probability=1/800000 \
       --run 'nbdcopy "$uri" $f'

# Count the number of bits set in the output file.  Easier to use
# Python here ...

$PYTHON -c '
import os
fh = open(os.environ["f"], "rb")
buf = bytearray(fh.read())
r = 0
for b in buf:
    if b != 0:
        r += bin(b).count("1")

print("non-zero bits: %d" % r)

assert(r > 20 and r < 180)
'
