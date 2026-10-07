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

requires $NBDKIT eval --version

# --can open / --can read are only successful when the export can be
# opened.

$NBDKIT -v -U - eval \
        get_size=' echo 64M ' \
        --run '$VG nbdinfo --can open "nbd+unix:///?socket=$unixsocket"'

$NBDKIT -v -U - eval \
        get_size=' echo 64M ' \
        --run '$VG nbdinfo --can read "nbd+unix:///?socket=$unixsocket"'

# But if the export cannot be opened, we expected them to fail.

st=0
$NBDKIT -v -U - eval \
        open='echo EIO go away >&2; exit 1' \
        get_size=' echo 64M ' \
        --run '$VG nbdinfo --can open "nbd+unix:///?socket=$unixsocket"' \
    || st=$?
test $st = 2

$NBDKIT -v -U - eval \
        open='echo EIO go away >&2; exit 1' \
        get_size=' echo 64M ' \
        --run '$VG nbdinfo --can read "nbd+unix:///?socket=$unixsocket"' \
    || st=$?
test $st = 2
