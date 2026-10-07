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

# Test nbdzero --fast-zero works.

. ../tests/functions.sh
set -e
set -x

requires nbdinfo --version
requires_uri
requires $NBDKIT --version
requires $NBDKIT data --filter=nozero --version

output=test-zero-fast.out
err=test-zero-fast.err
cleanup_fn rm -f $output $err

export output err

# discard --fast-zero implies zeroing
$NBDKIT -U - \
        data ' @1048576 1 @2097152 1 ' size=1G \
        --run ' nbddiscard --fast-zero -y "$uri" > $output 2> $err &&
                nbdinfo --map "$uri" >> $output '

cat $output
define expect <<\EOF
         0  1073741824    3  hole,zero
EOF
printf %s "$expect" | diff -u - $output
test -s $err

# zero --fast-zero fails if server lacks fast zero flag
$NBDKIT -U - \
        data ' @1048576 1 @2097152 1 ' size=1G \
        --filter=nozero zeromode=plugin fastzeromode=none \
        --run ' nbdzero --fast-zero -y "$uri" > $output 2> $err ;
                nbdinfo --map "$uri" >> $output '

cat $output
define expect <<\EOF
         0     1048576    3  hole,zero
   1048576       32768    0  data
   1081344     1015808    3  hole,zero
   2097152       32768    0  data
   2129920  1071611904    3  hole,zero
EOF
printf %s "$expect" | diff -u - $output
cat $err
grep "fast zero.*not supported" $err

# zero --fast-zero fails if server responds to flag with fast failure
$NBDKIT -U - \
        data ' @1048576 1 @2097152 1 ' size=1G \
        --filter=nozero zeromode=plugin fastzeromode=slow \
        --run ' nbdzero --fast-zero --yes "$uri" > $output 2> $err ;
                nbdinfo --map "$uri" >> $output '

cat $output
define expect <<\EOF
         0     1048576    3  hole,zero
   1048576       32768    0  data
   1081344     1015808    3  hole,zero
   2097152       32768    0  data
   2129920  1071611904    3  hole,zero
EOF
printf %s "$expect" | diff -u - $output
cat $err
grep "Operation not supported" $err
