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

# Create an nbdkit python plugin which checks the peer UID & GID.

import nbdkit


def config(key, value):
    global pid, uid, gid
    if key == "pid":
        pid = int(value)
    elif key == "uid":
        uid = int(value)
    elif key == "gid":
        gid = int(value)
    else:
        raise RuntimeError("unknown parameter: " + key)


def open(readonly):
    # Fail open() if either we cannot read the peer credentials or
    # they do not match the parameters.
    p = nbdkit.peer_pid()
    nbdkit.debug("nbdkit.peer_pid() = %d" % p)
    u = nbdkit.peer_uid()
    nbdkit.debug("nbdkit.peer_uid() = %d" % u)
    g = nbdkit.peer_gid()
    nbdkit.debug("nbdkit.peer_gid() = %d" % g)

    assert p == pid
    assert u == uid
    assert g == gid

    return 1


def get_size(h):
    return 0


def pread(h, count, offset):
    return bytearray(count)
