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

# Test the rotational filter.

source ./functions.sh
set -e
set -x
set -u

requires_run
requires_nbdinfo
requires_nbdsh_uri

# Check nbdinfo supports the --is flag (not RHEL 8).
requires nbdkit -r null --run 'nbdinfo --is readonly "$uri"'

# With no filter, nbdkit-memory-filter is not rotational.
nbdkit memory 1M --run '! nbdinfo --is rotational "$uri"'

# With the filter, nbdkit-memory-filter is rotational, because
# rotational=true is the default.
nbdkit memory 1M --filter=rotational --run 'nbdinfo --is rotational "$uri"'

# With the filter, set rotational=true explicitly.
nbdkit memory 1M --filter=rotational rotational=true \
       --run 'nbdinfo --is rotational "$uri"'

# With the filter, set rotational=false explicitly.
nbdkit memory 1M --filter=rotational rotational=false \
       --run '! nbdinfo --is rotational "$uri"'
