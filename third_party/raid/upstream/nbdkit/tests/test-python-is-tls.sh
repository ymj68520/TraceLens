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

script=$abs_top_srcdir/tests/python-is-tls.py
test -f "$script"

skip_if_valgrind "because Python code leaks memory"
requires_nbdinfo
requires_run
requires_tls_certificates
requires jq --version

out="test-python-is-tls.out"
rm -f $out
cleanup_fn rm -f $out

# Test without TLS.
nbdkit --tls=off python $script \
       --run 'nbdinfo --json --no-content "$uri"' > $out
cat $out
test "$( jq -c '.exports[0]."export-size"' $out )" -eq 0
test "$( jq -c '."TLS"' $out )" = "false"

# Test with TLS.
nbdkit --tls=require --tls-certificates="$pkidir" python $script \
       --run 'nbdinfo --json --no-content "$uri"' > $out
cat $out
test "$( jq -c '.exports[0]."export-size"' $out )" -eq 1
test "$( jq -c '."TLS"' $out )" = "true"
