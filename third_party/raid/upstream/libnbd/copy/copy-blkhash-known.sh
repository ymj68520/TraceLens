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

# Test --blkhash option.

. ../tests/functions.sh

set -e
set -x

requires $NBDKIT --exit-with-parent --version
requires $NBDKIT --exit-with-parent data --version

hashfile=copy-blkhash-known.hash
cleanup_fn rm -f $hashfile
rm -f $hashfile

do_test () {
    data="$1"
    hash="$2"
    expected="$3"

    export hash hashfile
    $NBDKIT -U - data "$data" \
            --run 'nbdcopy --blkhash=$hash --blkhash-file=$hashfile \
                           "$uri" null:'
    cat $hashfile
    test "$expected" = "$(cat $hashfile)"
}

# Instances of the data plugin and the corresponding hash that we
# previously cross-checked against blkhash's test/blkhash.py

do_test "" \
        sha256 \
        af5570f5a1810b7af78caf4bc70a660f0df51e42baf91d4de5b2328de0e83dfc

do_test '"hello"' \
        md5 \
        f741ac9ce55f5325906bb14e9c05d467

do_test '"hello"' \
        sha256 \
        337355feb53a5309d5aba92796223c2c84ffab930e706c01fef573a2722545e6

do_test '"hello"' \
        sha512 \
        eca04a593cf12ec4132993da709048e25a2f1be3526e132fb521ec9d41f023ec4018b3fd07b014a33e36bb5fa145b36991f431e62f9e1a93bebea6c9565682c1

do_test '"hello"' \
        md5/4 \
        8262896de34125dec173722c920e8bd0

do_test '"hello" @1048576 "goodbye"' \
        sha256 \
        61b8f3a8cea76e16eeff7ce27f1b7711c1f1e437f5038cec17773772a4bded28

do_test '"12345678"*512*256' \
        md5 \
        84fc21ac2f49ac283ff399378d834d1a

do_test '"12345678"*512*256' \
        sha256 \
        cbb388edd25e567b85f504c7b345497f9fb4f6bbf4e39768809184b9f9e678f8

do_test '"12345678"*512*256' \
        sha512/512k \
        379f7eb1628058c7abbc4c96941ac972074815ea9ef4aca95eefb2b4f9c29f64023fff8d966e9fddf08d07bdba548e75298917f10268fdf9ba636c2321a2214e
