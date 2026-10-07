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

# Test nbd+vsock:// URIs

source ./functions.sh
set -e
set -x

# vsock loopback support was only added in Linux kernel 5.6 and
# requires a particular kernel module to be loaded.
requires_linux_kernel_version 5.6
requires_vsock_support

# We need nbdinfo and URI support.
requires nbdinfo --version
requires_uri

requires $CUT --version

# This test requires nbdkit >= 1.16 which added the --vsock option.
requires $NBDKIT --version
minor=$( $NBDKIT --dump-config | grep ^version_minor | $CUT -d= -f2 )
requires test $minor -ge 16

requires $NBDKIT pattern --version

# Because vsock ports are 32 bits, we can basically pick one at random
# and be sure that it's not used.  However we must pick one >= 1024
# because the ports below this are privileged.
#
# libxml2 < 2.9 limited ports to 99,999,999, but that version is very
# old.  libxml2 only supports signed (ie. 31 bit) ports, so we only
# use 30 bits here for safety.
port=$(( 1024 + $RANDOM + ($RANDOM << 14) ))

# Form the NBD URI.  Don't rely on nbdkit $uri support since it didn't
# always support vsock, and anyway we want to test libnbd here.
# 1 == VMADDR_CID_LOCAL
export our_uri="nbd+vsock://1:$port"

$NBDKIT --vsock --port $port \
        pattern size=8M \
        --run 'nbdinfo "$our_uri"'
