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
requires $CMP /dev/null /dev/null
requires hexdump -C /dev/null

pidfile1=copy-nbd-to-nbd.pid1
pidfile2=copy-nbd-to-nbd.pid2
file1=copy-nbd-to-nbd.file1
file2=copy-nbd-to-nbd.file2
sock1=$(mktemp -u /tmp/libnbd-test-copy.XXXXXX)
sock2=$(mktemp -u /tmp/libnbd-test-copy.XXXXXX)
cleanup_fn rm -f $pidfile1 $pidfile2 $file1 $file2 $sock1 $sock2

$NBDKIT --exit-with-parent -f -v -P $pidfile1 -U $sock1 pattern size=10M &
wait_for_pidfile $NBDKIT $pidfile1

$NBDKIT --exit-with-parent -f -v -P $pidfile2 -U $sock2 memory size=10M &
wait_for_pidfile $NBDKIT $pidfile2

$VG nbdcopy "nbd+unix:///?socket=$sock1" "nbd+unix:///?socket=$sock2"

# Download the file from both servers and check they are the same.
$VG nbdcopy "nbd+unix:///?socket=$sock1" $file1
$VG nbdcopy "nbd+unix:///?socket=$sock2" $file2

ls -l $file1 $file2
$CMP $file1 $file2

# Test the data is at least non-zero.
test "$(hexdump -C $file1 | head -1)" = "00000000  00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 08  |................|"
