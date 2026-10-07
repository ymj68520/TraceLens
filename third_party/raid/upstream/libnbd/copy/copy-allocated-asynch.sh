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

# Check the --allocated option without --synchronous.

. ../tests/functions.sh

set -e
set -x

requires $NBDKIT --version
requires $NBDKIT --exit-with-parent --version
requires $NBDKIT null --version
requires $STAT --version

out=copy-allocated-asynch.out
cleanup_fn rm -f $out
rm -f $out

$VG nbdcopy --allocated --request-size=32K -- \
    [ $NBDKIT --exit-with-parent null size=32M ] \
    $out

echo Output:
ls -lsh $out

# The output file should be fully allocated 32M.
size="$( $STAT -c %s $out )"
balloc="$( $STAT -c %b $out )"
bsize="$( $STAT -c %B $out )"
alloc=$(( $balloc * $bsize ))

if [ "$size" -ne $(( 32 * 1024 * 1024)) ]; then
    echo "$0: file size is not 32M"
    exit 1
fi
if [ "$alloc" -ne $(( 32 * 1024 * 1024)) ]; then
    echo "$0: allocated size is not 32M"
    exit 1
fi
