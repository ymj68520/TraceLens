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

# Test the -v / --verbose option.

source ./functions.sh
set -e
set -x
set -u

requires_run
requires_plugin null
requires grep --version

# This should print the version of nbdkit to stderr.
nbdkit --verbose null --run true 2>&1 | grep 'debug: nbdkit 1\.'

# No debug statements should be printed on stdout.
if nbdkit --verbose null --run true 2>/dev/null | grep 'debug: '; then
    echo "ERROR: debug statements were printed on stdout instead of stderr"
    exit 1
fi

# Test -D nbdkit.environ=1 to dump the environment.
nbdkit_sentinel=42 \
    nbdkit --verbose -D nbdkit.environ=1 null --run true 2>&1 |
    grep 'debug: nbdkit_sentinel=42'

# Test escaping of debug strings, conveniently testable using bash $''
# escaping and -D nbdkit.environ=1
nbdkit_special=$'\a\b\t\n' \
    nbdkit --verbose -D nbdkit.environ=1 null --run true 2>&1 |
    grep 'debug: nbdkit_special=\\a\\b\\t\\n'
