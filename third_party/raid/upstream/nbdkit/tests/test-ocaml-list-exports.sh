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

plugin="./test-ocaml-plugin.so"
requires test -f $plugin

requires jq --version
requires_nbdinfo
requires_run

# libnbd 1.4.0 added support for --list but it was incomplete (did not
# fetch descriptions) until 1.4.1, so require a later version.
requires_libnbd_version 1.6

# Skip test because loading the OCaml plugin fails on macOS (darwin):
# nbdkit: error: cannot open plugin "./test-ocaml-plugin.so": dlopen(./test-ocaml-plugin.so, 0x000A): symbol not found in flat namespace '_caml_startup'
requires_not test "$(uname)" = "Darwin"

out="test-ocaml-list-exports.out"
rm -f $out
cleanup_fn rm -f $out

# Uses test_ocaml_plugin.ml.  Note the parameters are required as they
# are checked for another test.
nbdkit $plugin a=1 b=2 c=3 d=4 \
       --run 'nbdinfo --list --json "$uri"' > $out
cat $out

result="$( jq -c '[.exports[] | [."export-name", .description]]' $out )"
test "$result" = '[["name1","desc1"],["name2",null]]'
