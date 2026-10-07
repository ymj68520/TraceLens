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

# Tests various aspects of the .uri field.

. ../tests/functions.sh

set -e
set -x

requires $NBDKIT --version
requires $NBDKIT file --version
case $($NBDKIT file --version 2>&1) in
    *1.34.[012]* )
        echo "$0: skipping known double-free bug in $NBDKIT file dir="
        exit 77
esac
requires $NBDKIT -U - null --run 'test "$uri" != ""'
requires jq --version

# This test requires nbdkit >= 1.22.
minor=$( $NBDKIT --dump-config | grep ^version_minor | cut -d= -f2 )
requires test $minor -ge 22

d=info-uri.d
out=info-uri.out
rm -f $out
rm -rf $d
cleanup_fn rm -f $out
cleanup_fn rm -rf $d

# Create a test directory containing various known files.
mkdir $d
touch $d/"%%"          ;# requires percent-escaping
touch $d/"hello world" ;# requires escaping
touch $d/"リソース"     ;# tests UTF-8 support, broken in earlier nbdinfo

$NBDKIT -U - -r file dir=$d --run '$VG nbdinfo --json --list "$uri"' > $out
cat $out
jq . < $out

[[ $( jq -r '.exports[] | select(."export-name" == "%%") | .uri' < $out ) \
     =~ ^nbd\+unix:///%25%25\?socket= ]]
[[ $( jq -r '.exports[] | select(."export-name" == "hello world") | .uri' < $out ) \
     =~ ^nbd\+unix:///hello(%20|\+)world\?socket= ]]
[[ $( jq -r '.exports[] | select(."export-name" == "リソース") | .uri' < $out ) \
     =~ ^nbd\+unix:///%E3%83%AA%E3%82%BD%E3%83%BC%E3%82%B9\?socket= ]]
