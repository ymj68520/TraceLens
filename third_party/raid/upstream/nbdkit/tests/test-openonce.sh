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

requires_run
requires_plugin sh
requires_nbdsh_uri
# Requires explicit h.close() method, added in 1.16
requires_libnbd_version 1.16
requires dd --version
requires dd iflag=count_bytes </dev/null

log=openonce.log
rm -f $log
cleanup_fn rm -f $log

define plugin <<'EOF'

case "$1" in
     open)
         echo "plugin open $3" >>$log
         # return the export name as the handle
         echo "$3"
         ;;
     get_size)
         echo "plugin get_size $2" >>$log
         # return the export name as the size
         echo $2
         ;;
     pread)
         dd if=/dev/null count=$3 iflag=count_bytes
         ;;
     close)
         echo "plugin close $2" >>$log
         ;;
     *) exit 2 ;;
esac

EOF

define script <<'EOF'

import os

sock = os.getenv("unixsocket")

# Connect to the server with exportname="1M"
h.set_handle_name("h")
h.set_export_name("1M")
h.connect_unix(sock)
assert h.get_size() == 1024*1024

# Connect to "2M"
h2 = nbd.NBD()
h2.set_handle_name("h2")
h2.set_export_name("2M")
h2.connect_unix(sock)
assert h2.get_size() == 2*1024*1024

# Connect again to "1M".  There shouldn't be any open call in the plugin.
h3 = nbd.NBD()
h3.set_handle_name("h3")
h3.set_export_name("1M")
h3.connect_unix(sock)
assert h3.get_size() == 1024*1024

# Close handles 1 & 2.
h.close()
h2.close()

# Connect again to "2M".  There shouldn't be any open call in the plugin.
h4 = nbd.NBD()
h4.set_handle_name("h4")
h4.set_export_name("2M")
h4.connect_unix(sock)
assert h4.get_size() == 2*1024*1024

EOF

export log script
nbdkit -v sh - <<<"$plugin" \
       --filter=openonce \
       --run 'export unixsocket; nbdsh -c "$script"'

cat $log

# In the log we expect to see 2x open and 2x close.
test "$( grep "plugin open" $log | wc -l )" = 2
test "$( grep "plugin close" $log | wc -l )" = 2
