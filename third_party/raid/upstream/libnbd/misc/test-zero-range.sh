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

# Test nbdzero -o/-l works.

. ../tests/functions.sh
set -e
set -x

requires nbdinfo --version
requires_uri
requires $NBDKIT --version
requires $NBDKIT data --version

output=test-zero-range.out
cleanup_fn rm -f $output

export output

# Limit to tail of file that is already sparse
$NBDKIT -U - \
        data ' @1048576 1 @2097152 1 ' size=1G \
        --run ' nbdzero -y "$uri" -o 512M -l 512M &&
                nbdinfo --map "$uri" > $output '

cat $output
define expect <<\EOF
         0     1048576    3  hole,zero
   1048576       32768    0  data
   1081344     1015808    3  hole,zero
   2097152       32768    0  data
   2129920  1071611904    3  hole,zero
EOF
printf %s "$expect" | diff -u - $output

# Limit to head of file to see a change
$NBDKIT -U - \
        data ' @1048576 1 @2097152 1 ' size=1G \
        --run ' nbdzero -y "$uri" -l 2M &&
                nbdinfo --map "$uri" > $output '

cat $output
define expect <<\EOF
         0     2097152    3  hole,zero
   2097152       32768    0  data
   2129920  1071611904    3  hole,zero
EOF
printf %s "$expect" | diff -u - $output
