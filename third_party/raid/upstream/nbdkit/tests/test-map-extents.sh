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

# Test the map filter with extents.

source ./functions.sh
set -e
set -x
set -u

requires_run
requires_plugin data
requires_nbdinfo

out=map-extents.out
rm -f $out
cleanup_fn rm -f $out

define data <<'EOF'
# Underlying plugin:
# 0-1M  sparse
# 1M-2M data
@1M "1" * 1048576
# 2M-3M sparse
# 3M-4M data
@3M "1" * 1048576
# 4M-8M sparse
@8M
EOF

# This will map 1M-2M to 0, so the data there will be hidden and
# it should appear sparse.
define map <<'EOF'
--filter=map
map=1048576-2097151:0
EOF

define expected <<'EOF'
         0     3145728    3  hole,zero
   3145728     1048576    0  data
   4194304     4194304    3  hole,zero
EOF

# Run the test.
export out
nbdkit data "$data" $map \
       --run ' nbdinfo --map "$uri" > $out '

cat $out

# Check map as expected.
diff -uwB <(echo "$expected") $out
