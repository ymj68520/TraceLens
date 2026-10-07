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

# Test the spinning filter.

source ./functions.sh
set -e
set -x
set -u

requires guestfish --version

sock=$(mktemp -u /tmp/nbdkit-test-sock.XXXXXX)
pid=spinning-mkfs.pid
rm -f $pid
cleanup_fn rm -f $sock $pid

# Defaults:
#min_seek_time=10ms
#half_seek_time=200ms
#max_seek_time=500ms
min_seek_time=2ms
half_seek_time=20ms
max_seek_time=50ms

start_nbdkit -P $pid \
             -U $sock \
             memory 1G \
             --filter=spinning heads=3 \
             min-seek-time=$min_seek_time \
             half-seek-time=$half_seek_time \
             max-seek-time=$max_seek_time \
             -D spinning.verbose=1

# This doesn't really test the functionality of the filter, just that
# it isn't completely broken.  XXX
guestfish --rw --format=raw -a "nbd://?socket=$sock" <<EOF
  run
  -debug sh "head /sys/block/*/queue/rotational"
  part-disk /dev/sda gpt
  mkfs ext4 /dev/sda1
  mount /dev/sda1 /
  copy-in $srcdir/../filters/spinning /
  find /
EOF
