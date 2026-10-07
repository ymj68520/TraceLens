#!/usr/bin/env bash
# nbdkit
# Copyright Red Hat
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
# * Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright
# notice, this list of conditions and the following disclaimer in the
# documentation and/or other materials provided with the distribution.
#
# * Neither the name of Red Hat nor the names of its contributors may be
# used to endorse or promote products derived from this software without
# specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY RED HAT AND CONTRIBUTORS ''AS IS'' AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
# PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL RED HAT OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
# USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
# OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
# SUCH DAMAGE.

# Test that listing exports is denied.

source ./functions.sh
set -e
set -x
set -u

requires nbdsh --version
requires_nbdsh_uri
requires_nbdinfo
requires_run

# Listing exports should work in the ordinary case.
nbdkit -v null -D ip.rules=1 --filter=ip allow=all --run 'nbdinfo --list "$uri"'

# Listing exports should be denied in the early filtering case.
define script1 <<'EOF'
import os
uri = os.getenv('uri')
h = nbd.NBD()
h.set_opt_mode(True)
try:
    h.connect_uri(uri)
    h.opt_list(lambda *args: print(*args))
    assert False
except:
    # Expect connect_uri to fail.
    pass
EOF

export script1
nbdkit -v null \
       -D ip.rules=1 --filter=ip deny=all \
       --run 'export uri; nbdsh -c "$script1"'

# Same in the late filtering case.
define script2 <<'EOF'
import os
uri = os.getenv('uri')
h = nbd.NBD()
h.set_opt_mode(True)
try:
    h.connect_uri(uri)
    h.opt_list(lambda *args: print(*args))
    assert False
except:
    # Expect opt_list to fail.
    pass
EOF

export script2
nbdkit -v null \
       -D ip.rules=1 --filter=ip allow=dn:123 deny=all \
       --run 'export uri; nbdsh -c "$script2"'
