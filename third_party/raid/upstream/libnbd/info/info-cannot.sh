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

requires $NBDKIT --version
requires $NBDKIT memory --version

# Read-only nbdkit should not be writable.
$NBDKIT -v -U - -r memory 1M \
        --run '$VG nbdinfo --cannot write "nbd+unix:///?socket=$unixsocket"'

# Writable nbdkit isn't read-only.
$NBDKIT -v -U - memory 1M \
        --run '$VG nbdinfo --isnt read-only "nbd+unix:///?socket=$unixsocket"'

# Oldstyle NBD protocol doesn't support extended headers.
$NBDKIT -v -U - -o memory 1M \
        --run '$VG nbdinfo --hasnt extended-headers "nbd+unix:///?socket=$unixsocket"'
