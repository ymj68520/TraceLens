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

# Test nbdfuse [ nbdkit ] (using systemd socket activation).

. ../tests/functions.sh

set -e
set -x

requires_fuse
requires $NBDKIT --exit-with-parent --version
requires $CMP --version
requires $DD --version

if ! test -r /dev/urandom; then
    echo "$0: test skipped: /dev/urandom not readable"
    exit 77
fi

pidfile=test-nbdkit.pid
mp=test-nbdkit.d
data=test-nbdkit.data
cleanup_fn fusermount3 -u $mp
cleanup_fn rm -rf $mp
cleanup_fn rm -f $pidfile $data

mkdir -p $mp
$VG nbdfuse -P $pidfile $mp [ $NBDKIT --exit-with-parent memory size=10M ] &
wait_for_pidfile nbdfuse $pidfile

ls -al $mp

$DD if=/dev/urandom of=$data bs=1M count=10
# Use a weird block size when writing.  It's a bit pointless because
# something in the Linux/FUSE stack turns these into exact 4096 byte
# writes.
$DD if=$data of=$mp/nbd bs=65519 conv=nocreat,notrunc
$CMP $data $mp/nbd
