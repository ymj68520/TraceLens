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

# XXX This test needs to be enhanced to put some known content on the
# partition outside nbdkit then read it back from within nbdkit.

source ./functions.sh
set -e
set -x
set -u

requires_run
requires_nbdcopy
requires fdisk --version
requires stat --version
requires truncate --version

disk="partition-4k-gpt.disk"
out="partition-4k-gpt.part"
rm -f $disk $out
cleanup_fn rm -f $disk $out

# It would be nice to use sfdisk, but that utility doesn't support
# using a sector size different from the device block size (and no,
# adding "sector-size: 4096" to the script doesn't work, in fact it
# does entirely the wrong thing).

truncate -s 1G $disk
fdisk -b 4096 $disk <<EOF
g
n
p
1
256
+256m
p
w
EOF

# Run nbdkit with the partition filter.
nbdkit -f -v \
       --filter=partition file $disk partition-sectorsize=4k partition=1 \
       --run "nbdcopy \$uri $out"

ls -l $out

if [ "$( stat -L -c '%s' $out )" != $(( 256 * 1024 * 1024 )) ]; then
    echo "$0: unexpected size of output partition"
    exit 1
fi
