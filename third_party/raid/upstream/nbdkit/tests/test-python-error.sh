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

# Test the nbdkit.set_error function.
#
# The NBD protocol only supports specific errors, see:
# https://github.com/NetworkBlockDevice/nbd/blob/master/doc/proto.md#error-values

source ./functions.sh
set -e
set -x
set -u

script=$abs_top_srcdir/tests/python-error.py
test -f "$script"

skip_if_valgrind "because Python code leaks memory"
requires nbdsh --version

export script
nbdsh -c - <<'EOF'
import os

script = os.environ["script"]

errors = ["EPERM",
          "EIO",
          "ENOMEM",
          "EINVAL",
          "ENOSPC",
          # nbdkit maps EOVERFLOW to EINVAL unless the DF flag
          # is set, so this is hard to test.
          #"EOVERFLOW",
          # nbdkit maps ENOTSUP to EINVAL unless FAST_ZERO is set.
          #"ENOTSUP",
          "ESHUTDOWN"]

for err in errors:
    h = nbd.NBD()
    h.connect_command(["nbdkit", "-s", "-v", "--exit-with-parent",
                       "python", script, "error=" + err])
    try:
        # This is expected to throw an exception
        h.pread(1,0)
        assert False
    except nbd.Error as ex:
        print("errno thrown is %s" % ex.errno, flush=True)
        assert ex.errno == err

    h.shutdown()
EOF
