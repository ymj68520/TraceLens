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

requires_root
requires_caps cap_sys_admin
requires $NBDKIT --exit-with-parent --version
requires test -r /sys/module/nbd
requires nbd-client --version
# /dev/nbd0 must not be in use.
requires_not nbd-client -c /dev/nbd0

pidfile1=copy-nbd-to-small-block-error.pid1
pidfile2=copy-nbd-to-small-block-error.pid2
sock1=$(mktemp -u /tmp/libnbd-test-copy.XXXXXX)
sock2=$(mktemp -u /tmp/libnbd-test-copy.XXXXXX)
cleanup_fn rm -f $pidfile1 $pidfile2 $sock1 $sock2
cleanup_fn nbd-client -d /dev/nbd0

$NBDKIT --exit-with-parent -f -v -P $pidfile1 -U $sock1 pattern size=10M &
wait_for_pidfile $NBDKIT $pidfile1
$NBDKIT --exit-with-parent -f -v -P $pidfile2 -U $sock2 memory size=5M &
wait_for_pidfile $NBDKIT $pidfile2

nbd-client -unix $sock2 /dev/nbd0 -b 512

# The source is larger than the destination device so we expect this
# test to fail.  In the log you should see:
#   nbdcopy: error: destination size (...) is smaller than source size (...)
if nbdcopy -v "nbd+unix:///?socket=$sock1" /dev/nbd0; then
    echo "$0: expected this test to fail"
    exit 1
fi
