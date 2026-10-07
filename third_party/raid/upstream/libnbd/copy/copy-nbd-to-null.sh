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

pidfile=copy-nbd-to-null.pid
file=copy-nbd-to-null.file
sock=$(mktemp -u /tmp/libnbd-test-copy.XXXXXX)
cleanup_fn rm -f $pidfile $file $sock

$NBDKIT --exit-with-parent -f -v -P $pidfile -U $sock pattern size=10M &
wait_for_pidfile $NBDKIT $pidfile

$VG nbdcopy "nbd+unix:///?socket=$sock" null:
