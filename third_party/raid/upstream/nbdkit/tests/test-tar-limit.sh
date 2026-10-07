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

# Test the tar filter and tar-limit filter.

source ./functions.sh
set -e
set -x
set -u

requires_run
requires test -f disk
requires tar --version
requires test -f disk
requires_nbdinfo

tar_bad=tar-limit-bad.tar
tar_good=tar-limit-good.tar
tar_filler=tar-limit-filler.img
files="$tar_bad $tar_good $tar_filler"
rm -f $files
cleanup_fn rm -f $files

# Create two tar files, one where the disk is located before an
# arbitrary boundary and one after.
truncate -s 1M $tar_filler
tar cf $tar_good disk
tar cf $tar_bad $tar_filler disk

# Check we can read the good disk and reject the bad disk.
cmd="nbdkit file --filter=tar tar-entry=disk tar-limit=131072"

$cmd $tar_good --run 'nbdinfo "$uri"'

if $cmd $tar_bad --run 'nbdinfo "$uri"' ; then
    echo "ERROR: $0: expected $tar_bad to fail"
    exit 1
fi
