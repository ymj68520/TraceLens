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

# Check the --destination-is-zero + --synchronous options.

. ../tests/functions.sh

set -e
set -x

requires $CMP --version
requires $DD --version
requires $TRUNCATE --version
requires $STAT --version
requires test -r /dev/zero

inp=copy-destination-zero-synch.in
out=copy-destination-zero-synch.out
cleanup_fn rm -f $inp $out
rm -f $inp $out

# When using this option we implicitly promise that the output is
# zero.  It may be allocated or sparse.
$DD if=/dev/zero of=$out bs=1024k count=32

# The input can be sparse.
$TRUNCATE -r $out $inp

$VG nbdcopy --destination-is-zero --synchronous --request-size=32K $inp $out

echo Output:
ls -lsh $out

# The output should be 32M in size and all zero.  It may or may not
# still be allocated.
size="$( $STAT -c %s $out )"

if [ "$size" -ne $(( 32 * 1024 * 1024)) ]; then
    echo "$0: file size is not 32M"
    exit 1
fi

$CMP $inp $out
