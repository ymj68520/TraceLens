#!/usr/bin/env bash
# nbd client library in userspace
# Copyright Red Hat
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

# Test nbdfuse file mode + nbdkit-null-plugin.

. ../tests/functions.sh

set -e
set -x

requires_fuse
requires $NBDKIT --exit-with-parent --version
requires $TRUNCATE --version

pidfile=test-nbdkit-file-null.pid
mp=test-nbdkit-file-null
rm -f $pidfile $mp
cleanup_fn fusermount3 -u $mp
cleanup_fn rm -f $pidfile $mp

# Create the underlying file/mountpoint as non-zero sized.
$TRUNCATE -s 1024 $mp

$VG nbdfuse -P $pidfile $mp [ $NBDKIT -r --exit-with-parent null ] &
wait_for_pidfile nbdfuse $pidfile

ls -l $mp

test -f $mp

# Check the size is zero.
# Note the underlying file (created above) is non-zero sized.
test ! -s $mp

# This would be a good test, but access($mp, W_OK) succeeds. XXX
# Check the file is read-only.
#test ! -w $mp
