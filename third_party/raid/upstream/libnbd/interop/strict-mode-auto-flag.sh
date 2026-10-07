#!/usr/bin/env bash
# nbd client library in userspace
# Copyright Red Hat
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

# Test effect of AUTO_FLAG bit in set_strict_mode()

source ../tests/functions.sh
set -e
set -x

requires $TRUNCATE --version
requires $QEMU_NBD --version
requires nbdsh --version

file="strict-mode-auto-flag.file"
rm -f $file
cleanup_fn rm -f $file

$TRUNCATE -s 1M $file

# Unconditional part of test: behavior when extended headers are not in use
export QEMU_NBD
$VG nbdsh -c '
import errno, os

qemu_nbd = os.environ["QEMU_NBD"]

h.set_request_extended_headers(False)
args = [qemu_nbd, "-f", "raw", "'"$file"'"]
h.connect_systemd_socket_activation(args)
assert h.get_extended_headers_negotiated() is False

# STRICT_AUTO_FLAG and STRICT_COMMANDS are on by default
flags = h.get_strict_mode()
assert flags & nbd.STRICT_AUTO_FLAG
assert flags & nbd.STRICT_COMMANDS

# Under STRICT_AUTO_FLAG, using or omitting flag does not matter; client
# side auto-corrects the flag before passing to server
h.pwrite(b"1"*512, 0, 0)
h.pwrite(b"2"*512, 0, nbd.CMD_FLAG_PAYLOAD_LEN)

# Without STRICT_AUTO_FLAG but still STRICT_COMMANDS, client side now sees
# attempts to use the flag as invalid
flags = flags & ~nbd.STRICT_AUTO_FLAG
h.set_strict_mode(flags)
h.pwrite(b"3"*512, 0, 0)
stats = h.stats_bytes_sent()
try:
  h.pwrite(b"4"*512, 0, nbd.CMD_FLAG_PAYLOAD_LEN)
  assert False
except nbd.Error as e:
  assert e.errnum == errno.EINVAL
assert stats == h.stats_bytes_sent()

# Warning: fragile test ahead.  Without STRICT_COMMANDS, we send unexpected
# flag to qemu, and expect failure. For qemu <= 8.1, this is safe (those
# versions did not know the flag, and correctly reject unknown flags with
# NBD_EINVAL). For qemu 8.2, this also works (qemu knows the flag, but warns
# that we were not supposed to send it without extended headers). But if
# future qemu versions change to start silently ignoring the flag (after all,
# a write command obviously has a payload even without extended headers, so
# the flag is redundant for NBD_CMD_WRITE), then we may need to tweak this.
flags = flags & ~nbd.STRICT_COMMANDS
h.set_strict_mode(flags)
h.pwrite(b"5"*512, 0, 0)
stats = h.stats_bytes_sent()
try:
  h.pwrite(b"6"*512, 0, nbd.CMD_FLAG_PAYLOAD_LEN)
  print("Did newer qemu change behavior?")
  assert False
except nbd.Error as e:
  assert e.errnum == errno.EINVAL
assert stats < h.stats_bytes_sent()

h.shutdown()
'

# Conditional part of test: only run if qemu supports extended headers
requires nbdinfo --has extended-headers -- [ $QEMU_NBD -r -f raw "$file" ]
export QEMU_NBD
$VG nbdsh -c '
import errno, os

qemu_nbd = os.environ["QEMU_NBD"]

args = [qemu_nbd, "-f", "raw", "'"$file"'"]
h.connect_systemd_socket_activation(args)
assert h.get_extended_headers_negotiated() is True

# STRICT_AUTO_FLAG and STRICT_COMMANDS are on by default
flags = h.get_strict_mode()
assert flags & nbd.STRICT_AUTO_FLAG
assert flags & nbd.STRICT_COMMANDS

# Under STRICT_AUTO_FLAG, using or omitting flag does not matter; client
# side auto-corrects the flag before passing to server
h.pwrite(b"1"*512, 0, 0)
h.pwrite(b"2"*512, 0, nbd.CMD_FLAG_PAYLOAD_LEN)

# Without STRICT_AUTO_FLAG but still STRICT_COMMANDS, client side now sees
# attempts to omit the flag as invalid
flags = flags & ~nbd.STRICT_AUTO_FLAG
h.set_strict_mode(flags)
h.pwrite(b"3"*512, 0, nbd.CMD_FLAG_PAYLOAD_LEN)
stats = h.stats_bytes_sent()
try:
  h.pwrite(b"4"*512, 0, 0)
  assert False
except nbd.Error as e:
  assert e.errnum == errno.EINVAL
assert stats == h.stats_bytes_sent()

# Warning: fragile test ahead.  Without STRICT_COMMANDS, omitting the flag
# is a protocol violation. qemu 8.2 silently ignores the violation; but a
# future qemu might start failing the command, at which point we would need
# to tweak this part of the test.
flags = flags & ~nbd.STRICT_COMMANDS
h.set_strict_mode(flags)
h.pwrite(b"5"*512, 0, nbd.CMD_FLAG_PAYLOAD_LEN)
stats = h.stats_bytes_sent()
try:
  h.pwrite(b"6"*512, 0, 0)
except nbd.Error:
  print("Did newer qemu change behavior?")
  assert False
assert stats < h.stats_bytes_sent()

h.shutdown()
'
