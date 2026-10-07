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
requires $NBDKIT -U - --filter=blocksize-policy data 1 --run 'test "$uri" != ""'

out=info-map-large-extent.out
cleanup_fn rm -f $out
rm -f $out

# nbdkit < 1.44 had a bug where 4G large extents would truncate larger than
# the aligned request; whether or not nbdkit is fixed, we can work around it.
$NBDKIT -U - data data='@4294967296 1 @^512' \
        --filter=blocksize-policy blocksize-minimum=512 \
        --run '$VG nbdinfo --map "$uri"' > $out

cat $out

diff -u - $out <<EOF
         0  4294967296    3  hole,zero
4294967296         512    0  data
EOF
