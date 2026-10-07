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

# Used in conjunction with test-timeout.sh

import select
import socket
import sys
import time

unixsocket = sys.argv[1]

sockets = []
t1 = time.monotonic()
for i in range(5):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    print("test-timeout: opened socket %d" % s.fileno(),
          file=sys.stderr, flush=True)
    s.connect(unixsocket)
    # Read and discard the initial greeting from nbdkit.
    b = s.recv(18)
    sockets.append(s)

while sockets:
    ready = select.select(sockets, [], [], 30)[0]
    for s in ready:
        b = s.recv(1024)
        if not b:
            t2 = time.monotonic()
            print("test-timeout: closed socket %d after %ds" %
                  (s.fileno(), t2-t1),
                  file=sys.stderr, flush=True)
            sockets.remove(s)
            s.close()

# At least 5 seconds must have passed before all sockets closed.
t2 = time.monotonic()
print("test-timeout: total elapsed time: %ds" % (t2-t1),
      file=sys.stderr, flush=True)
assert t2-t1 >= 5
