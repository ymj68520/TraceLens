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

. ../tests/functions.sh

set -e
set -x

requires $NBDKIT --exit-with-parent --version
requires $CMP --version
requires $DD --version
requires $DD oflag=seek_bytes </dev/null
requires $STAT --version
requires test -r /dev/urandom
requires test -r /dev/zero

file=copy-file-to-nbd.file
file2=copy-file-to-nbd.file2
pidfile=copy-file-to-nbd.pid
sock=$(mktemp -u /tmp/libnbd-test-copy.XXXXXX)
cleanup_fn rm -f $file $file2 $pidfile $sock

# Create a random partially sparse file.
touch $file
for i in `seq 1 100`; do
    $DD if=/dev/urandom of=$file ibs=512 count=1 \
        oflag=seek_bytes seek=$((RANDOM * 9973)) conv=notrunc
    $DD if=/dev/zero of=$file ibs=512 count=1 \
        oflag=seek_bytes seek=$((RANDOM * 9973)) conv=notrunc
done
size="$( $STAT -c %s $file )"

$NBDKIT --exit-with-parent -f -v -P $pidfile -U $sock memory size=$size &
wait_for_pidfile $NBDKIT $pidfile

$VG nbdcopy $file "nbd+unix:///?socket=$sock"
$VG nbdcopy "nbd+unix:///?socket=$sock" $file2

ls -l $file $file2
$CMP $file $file2
