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

requires $QEMU_NBD --pid-file=test.pid --version
requires qemu-img --version
requires $CMP --version
requires $DD --version
requires $DD oflag=seek_bytes </dev/null
requires $STAT --version
requires test -r /dev/urandom
requires test -r /dev/zero
requires $TRUNCATE --version

file=copy-file-to-qcow2.file
file2=copy-file-to-qcow2.file2
qcow2=copy-file-to-qcow2.qcow2
pid=copy-file-to-qcow2.pid
sock=$(mktemp -u /tmp/libnbd-test-copy.XXXXXX)
rm -f $file $file2 $qcow2 $pid $sock
cleanup_fn rm -f $file $file2 $qcow2 $pid $sock

# Create a random partially sparse file.
touch $file
for i in `seq 1 100`; do
    $DD if=/dev/urandom of=$file ibs=512 count=1 \
        oflag=seek_bytes seek=$((RANDOM * 9973)) conv=notrunc
    $DD if=/dev/zero of=$file ibs=512 count=1 \
        oflag=seek_bytes seek=$((RANDOM * 9973)) conv=notrunc
done
size="$( $STAT -c %s $file )"

# Create the empty target qcow2 file.
qemu-img create -f qcow2 $qcow2 $size

# Run qemu-nbd as a separate process so that we can copy to and from
# the single process in two separate operations.
$QEMU_NBD -f qcow2 --cache=writeback -t --socket=$sock --pid-file=$pid $qcow2 &
cleanup_fn kill $!

wait_for_pidfile qemu-nbd $pid

$VG nbdcopy $file "nbd+unix:///?socket=$sock"
$VG nbdcopy "nbd+unix:///?socket=$sock" $file2

ls -l $file $file2

# Because qemu/qcow2 only supports whole sectors, we have to truncate
# the copied out file to the expected size before comparing.
$TRUNCATE -s $size $file2

$CMP $file $file2
