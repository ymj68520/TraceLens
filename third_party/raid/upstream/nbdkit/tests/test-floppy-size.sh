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

# Test the floppy / FAT32 plugin with the size= parameter.

source ./functions.sh
set -e
set -x
set -u

requires_plugin floppy
requires guestfish --version

sock=$(mktemp -u /tmp/nbdkit-test-sock.XXXXXX)
files="floppy-size.pid $sock"
rm -f $files
cleanup_fn rm -f $files

# When testing this we need to use a directory which won't change
# during the test (so not the current directory).
start_nbdkit -P floppy-size.pid -U $sock \
             --filter=cow \
             floppy $srcdir/../plugins/floppy size=2G

# Check the floppy content.
guestfish --rw --format=raw -a "nbd://?socket=$sock" -m /dev/sda1 <<'EOF'
  ll /floppy.c
  ll /nbdkit-floppy-plugin.pod

# Because of size= parameter there should be enough free space
# to write a large file.
  df-h
  fill-pattern hello 100M /fill
EOF
