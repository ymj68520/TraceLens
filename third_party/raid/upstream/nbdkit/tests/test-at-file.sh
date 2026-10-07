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

# Test @PATH (reads key=value parameters from PATH).

source ./functions.sh
set -e
set -x
set -u

export LANG=C

requires_run
requires_plugin sh

out="$PWD/at-file.out"
rm -f "$out"
cleanup_fn rm -f "$out"

# This custom plugin will log all parameters to $out.
define plugin <<'EOF'
#!/usr/bin/env bash
case "$1" in
    config)
        case "$2" in
            out) # output file
                ln -sf "$(realpath "$3")" $tmpdir/out
                ;;
            *) # any other parameter gets written to the output file
                echo "$2"="$3" >> $tmpdir/out
                ;;
        esac
        ;;
    magic_config_key) echo "magic" ;;
    *) exit  2;;
esac
EOF

# Run each test and check the output is as expected.

expected=$srcdir/test-at-file/1.expected
params="@$srcdir/test-at-file/1.input"

rm -f "$out"
touch "$out"
nbdkit -fv sh - <<<"$plugin" out="$out" $params --run true
diff -u $expected $out

expected=$srcdir/test-at-file/2.expected
params="@$srcdir/test-at-file/2.input"

rm -f "$out"
touch "$out"
nbdkit -fv sh - <<<"$plugin" out="$out" $params --run true
diff -u $expected $out

expected=$srcdir/test-at-file/3.expected
params="A=1 @$srcdir/test-at-file/3a.input B=2 @$srcdir/test-at-file/3b.input C=3"

rm -f "$out"
touch "$out"
nbdkit -fv sh - <<<"$plugin" out="$out" $params --run true
diff -u $expected $out

expected=$srcdir/test-at-file/4.expected
params="A=1 @$srcdir/test-at-file/4a.input B=2 @$srcdir/test-at-file/4b.input C=3"

rm -f "$out"
touch "$out"
nbdkit -fv sh - <<<"$plugin" out="$out" $params --run true
diff -u $expected $out
