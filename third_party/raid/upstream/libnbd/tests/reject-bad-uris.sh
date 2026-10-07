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

# Test some CVEs that affected nbd+ssh URIs and should now cause them
# to be rejected.

source ./functions.sh
set -e
set -x

# We need nbdinfo and URI support.
requires nbdinfo --version
requires_uri

# SSH must be available for nbd+ssh URIs to work at all.
requires ssh -V

out=reject-bad-uris.out
rm -f $out
cleanup_fn rm -f $out

# These are all expected to fail.  We check the error message is
# expected.
nbdinfo 'nbd+ssh://-oProxyCommand=glxgears' >& $out ||:
cat $out
grep "hostname contains invalid characters" $out

nbdinfo 'nbd+ssh://localhost/?socket=%2Ftmp%2Fnbd.sock%3Bid%20%3E%2Ftmp%2Flibnbd_poc' >& $out ||:
cat $out
grep "socket.*rejected.*contains shell metacharacters" $out

nbdinfo 'nbd+ssh://localhost/?nbd-port=10809%3Buname%20-a%20%3E%2Ftmp%2Flibnbd_poc' >& $out ||:
cat $out
grep "nbd-port.*rejected.*contains shell metacharacters" $out
