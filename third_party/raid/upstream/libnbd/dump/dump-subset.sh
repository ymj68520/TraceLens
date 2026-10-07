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
requires $NBDKIT pattern --dump-plugin
requires $NBDKIT -U - null --run 'test "$uri" != ""'
requires nbdsh -c 'exit(not h.supports_uri())'

output=dump-subset.out
rm -f $output
cleanup_fn rm -f $output

$NBDKIT -U - pattern size=100 --run 'nbddump --offset=15 --length=33 "$uri"' > $output

# Repeat with alternate spellings
$NBDKIT -U - pattern size=100 --run 'nbddump --skip 15 --limit 33 "$uri"' >> $output

cat $output

if [ "$(cat $output)" != '000000000f: 08 00 00 00 00 00 00 00  10 00 00 00 00 00 00 00 |................|
000000001f: 18 00 00 00 00 00 00 00  20 00 00 00 00 00 00 00 |........ .......|
000000002f: 28                                               |(               |
000000000f: 08 00 00 00 00 00 00 00  10 00 00 00 00 00 00 00 |................|
000000001f: 18 00 00 00 00 00 00 00  20 00 00 00 00 00 00 00 |........ .......|
000000002f: 28                                               |(               |' ]; then
    echo "$0: unexpected output from nbddump command"
    exit 1
fi
