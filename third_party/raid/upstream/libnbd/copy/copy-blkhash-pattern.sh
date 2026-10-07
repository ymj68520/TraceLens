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

# Test --blkhash option against a large plugin with known content.

. ../tests/functions.sh

set -e
set -x

requires $NBDKIT --exit-with-parent --version
requires $NBDKIT --exit-with-parent pattern --version

hashfile_sha256=copy-blkhash-pattern.hash256
hashfile_sha512=copy-blkhash-pattern.hash512
cleanup_fn rm -f $hashfile_sha256 $hashfile_sha512
rm -f $hashfile_sha256 $hashfile_sha512

export hashfile_sha256 hashfile_sha512

expected_sha256=6750a1c3d78e46eaffb0d094624825dea88f0c7098b2424fce776c0748442649
expected_sha512=aef2905a223b2b9b565374ce9671bcb434fc944b0a108c8b5b98769d830b6c61b9567de177791a092514675c3a3e0740758c6a5a171ae71d844c60315f07e334

$NBDKIT -U - pattern 1G \
        --run '
        nbdcopy --blkhash --blkhash-file=$hashfile_sha256 "$uri" null: &&
        nbdcopy --blkhash=sha512/512k --blkhash-file=$hashfile_sha512 \
                "$uri" null:
'
cat $hashfile_sha256
test "$expected_sha256" = "$(cat $hashfile_sha256)"

cat $hashfile_sha512
test "$expected_sha512" = "$(cat $hashfile_sha512)"
