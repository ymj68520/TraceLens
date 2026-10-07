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

# Test interaction with nbdkit, and for correct global handling over -c.

. ../tests/functions.sh
requires $NBDKIT --exit-with-parent --version
requires nbdsh -c 'exit(not h.supports_uri())'

sock=$(mktemp -u /tmp/libnbd-test-nbdsh.XXXXXX)
pidfile=test-pattern.pid
cleanup_fn rm -f $sock $pidfile
$NBDKIT -v -P $pidfile --exit-with-parent -U $sock pattern size=1m &
wait_for_pidfile $NBDKIT $pidfile

nbdsh -u "nbd+unix://?socket=$sock" \
    -c '
def size():
  return h.get_size()
' \
    -c 'assert 1024*1024 == size()' \
    -c 'assert h.pread(8, 8) == b"\x00\x00\x00\x00\x00\x00\x00\x08"'
