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

# Check the Python plugin binding for nbdkit.read_password by passing
# in a password=+<file> parameter and verifying that the password
# returned matches the <file> contents.

source ./functions.sh
set -e
set -x
set -u

script=$abs_top_srcdir/tests/python-password.py
test -f "$script"

skip_if_valgrind "because Python code leaks memory"
requires nbdsh --version

password_file="python-password.txt"
rm -f $password_file
cleanup_fn rm -f $password_file

password="testing 1 2 3"
echo "$password" > $password_file

export password password_file script
nbdsh -c - <<'EOF'
import os

expected_password = os.environ["password"]
password_file = os.environ["password_file"]
script = os.environ["script"]

h.connect_command(["nbdkit", "-s", "-v", "--exit-with-parent",
                   "python", script,
                   "password=+" + password_file])
size = h.get_size()
assert size == len(expected_password)
actual_password = h.pread(size, 0)
print("actual_password = %s" % actual_password)
assert actual_password.decode("ascii") == expected_password
h.shutdown()
EOF
