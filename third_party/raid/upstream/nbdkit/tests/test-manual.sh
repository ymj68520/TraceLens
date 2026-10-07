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

# Test each option appears in the main nbdkit(1) manual page.

source ./functions.sh
set -e
set -x
set -u

requires tr --version

# If these fail it's probably because you ran the script by hand.
test -n "$srcdir"
podfile=$srcdir/../docs/nbdkit.pod
test -f "$podfile"

# Windows uses CRLF line endings, so we have to remove the CR.
nocr="tr -d '\r'"

for i in $(nbdkit --short-options | $nocr) $(nbdkit --long-options | $nocr); do
    case "$i" in
        # Skip some options that we don't want to document.
        --print-url) ;;         # alias of --print-uri
        --show-uri) ;;          # alias of --print-uri
        --show-url) ;;          # alias of --print-uri
        --time-out) ;;          # alias of --timeout

        # Anything else is tested.
        *)
            grep '^=item B<'$i'[=>]' $podfile
    esac
done
