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

# Check the --allocated --destination-is-zero --synchronous options.

. ../tests/functions.sh

set -e
set -x

requires $CMP --version
requires $TRUNCATE --version
requires $STAT --version
requires_sparse_and_preallocated_files

inp=copy-allocated-destination-zero-synch.in
out=copy-allocated-destination-zero-synch.out
cleanup_fn rm -f $inp $out
rm -f $inp $out

$TRUNCATE -s $((32 * 1024 * 1024)) $out
$TRUNCATE -r $out $inp

$VG nbdcopy --allocated --destination-is-zero --synchronous --request-size=32K \
    $inp $out

echo Output:
ls -lsh $out

# The output should be 32M, all zero, and fully allocated.
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

$CMP $inp $out
