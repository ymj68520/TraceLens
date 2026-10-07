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

requires $PYTHON --version

# Python tests all fail on macOS because of SIP misfeature.
requires_not test "$(uname)" = "Darwin"

# Requires libxml2 for h.get_uri
requires_uri

# Requires nbdkit >= 1.47 supporting --port=0 properly.
requires $NBDKIT --version
minor=$( $NBDKIT --dump-config | grep ^version_minor | $CUT -d= -f2 )
requires test $minor -ge 47

# Check the host supports IPv6.
requires ip -V
requires bash -c 'ip -o -6 addr show scope host | grep inet6'

define script <<'EOF'
import nbd
import sys

h = nbd.NBD()
port = sys.argv[1]
addr = ("AF_INET6", ("::1", port))
h.aio_connect(addr)
while h.aio_is_connecting():
    h.poll(1)
assert h.aio_is_ready()

# libnbd should be able to form a URI from this address.
uri = h.get_uri()
print("uri:", uri)
assert uri == ("nbd://[::1]:%s/" % port)
EOF
export script

$NBDKIT --port=0 null --run '$PYTHON -c "$script" "$port"'
