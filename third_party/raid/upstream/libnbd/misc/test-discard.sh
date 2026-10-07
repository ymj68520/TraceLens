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

# Test nbddiscard works.

. ../tests/functions.sh
set -e
set -x

requires nbdinfo --version
requires_uri
requires $NBDKIT --version
requires $NBDKIT data --version

output=test-discard.out
cleanup_fn rm -f $output

export output
$NBDKIT -U - \
        data ' @1048576 1 @2097152 1 ' size=1G \
        --run ' nbddiscard -y "$uri" && nbdinfo --map "$uri" > $output '

cat $output
grep -E '0[[:space:]]+1073741824[[:space:]]+3[[:space:]]+hole,zero' $output
