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

source ./functions.sh
set -e
set -x
set -u

fail=0

# Test various means for crippling extents, for interop testing.

requires_run
requires_filter noextents
requires_nbdsh_uri

fail=0

# By default, the memory plugin advertises extents, and starts with a hole
nbdkit memory 1M --run 'nbdsh --base -u "$uri" -c - <<\EOF
def f(context, offset, entries, err):
  assert entries == [ 1024*1024, nbd.STATE_HOLE | nbd.STATE_ZERO]

assert h.get_structured_replies_negotiated() is True
assert h.can_meta_context(nbd.CONTEXT_BASE_ALLOCATION) is True
h.block_status(1024*1024, 0, f)
EOF
' || fail=1

# Even when a plugin or filter sets can_extents false, nbdkit still
# synthesizes one that advertises all data
nbdkit --filter=noextents memory 1M --run 'nbdsh --base -u "$uri" -c - <<\EOF
def f(context, offset, entries, err):
  assert entries == [ 1024*1024, 0]

assert h.get_structured_replies_negotiated() is True
assert h.can_meta_context(nbd.CONTEXT_BASE_ALLOCATION) is True
h.block_status(1024*1024, 0, f)
EOF
' || fail=1

# Disabling meta contexts prevents extents, but still allows structured
# replies; libnbd 1.18 errors out on can_meta_context in that case, but
# other versions of libnbd gracefully treat it as false
nbdkit --no-meta-contexts memory 1M --run 'nbdsh --base -u "$uri" -c - <<\EOF
assert h.get_structured_replies_negotiated() is True
try:
  ret = h.can_meta_context(nbd.CONTEXT_BASE_ALLOCATION)
  assert ret is False
except nbd.Error:
  print("treating libnbd error as meta context unsupported")
EOF
' || fail=1

# Disabling structured replies prevents extents as a side effect
nbdkit --no-sr memory 1M --run 'nbdsh --base -u "$uri" -c - <<\EOF
assert h.get_protocol() == "newstyle-fixed"
assert h.get_structured_replies_negotiated() is False
assert h.can_meta_context(nbd.CONTEXT_BASE_ALLOCATION) is False
EOF
' || fail=1

# Disabling fixed newstyle negotiation prevents structured replies
nbdkit --mask-handshake=0 memory 1M --run 'nbdsh --base -u "$uri" -c - <<\EOF
assert h.get_protocol() == "newstyle"
assert h.get_structured_replies_negotiated() is False
assert h.can_meta_context(nbd.CONTEXT_BASE_ALLOCATION) is False
EOF
' || fail=1

# Oldstyle protocol prevents structured replies
nbdkit --oldstyle memory 1M --run 'nbdsh --base -u "$uri" -c - <<\EOF
assert h.get_protocol() == "oldstyle"
assert h.get_structured_replies_negotiated() is False
assert h.can_meta_context(nbd.CONTEXT_BASE_ALLOCATION) is False
EOF
' || fail=1

exit $fail
