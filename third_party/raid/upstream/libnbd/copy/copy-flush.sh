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

# Check that we call flush if the --flush option is used.

. ../tests/functions.sh

set -e
set -x

requires $NBDKIT --version
requires $NBDKIT --exit-with-parent --version
requires $NBDKIT data --version
requires $NBDKIT eval --version
requires tail --version

out=copy-flush.out
cleanup_fn rm -f $out
rm -f $out

$VG nbdcopy --flush --request-size=32K -- \
    [ $NBDKIT --exit-with-parent data data='
              1
              @33554432 1
              ' ] \
    [ $NBDKIT --exit-with-parent eval \
              get_size=' echo 7E ' \
              pwrite=" cat >/dev/null; echo \$@ >> $out " \
              flush=" echo \$@ >> $out " ]

echo Output:
cat $out

# There must be a flush command, and it must be the last command.
tail -1 $out | grep flush
