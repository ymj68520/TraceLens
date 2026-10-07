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

# Test use of block status payload for server filtering

source ../tests/functions.sh
set -e
set -x

requires qemu-img bitmap --help
# This test uses the qemu-nbd -A and -B options.
requires $QEMU_NBD -A -BA --version
requires nbdsh --version

file="block-status-payload.qcow2"
rm -f $file
cleanup_fn rm -f $file

# Create sparse file with two bitmaps.
qemu-img create -f qcow2 $file 1M
qemu-img bitmap --add --enable -f qcow2 $file bitmap0
qemu-img bitmap --add --enable -f qcow2 $file bitmap1

# Unconditional part of test: qemu should not advertise block status payload
# support if extended headers are not in use
export QEMU_NBD
$VG nbdsh -c '
import os

qemu_nbd = os.environ["QEMU_NBD"]

h.set_request_extended_headers(False)
h.add_meta_context("base:allocation")
h.add_meta_context("qemu:allocation-depth")
h.add_meta_context("qemu:dirty-bitmap:bitmap0")
h.add_meta_context("qemu:dirty-bitmap:bitmap1")
h.set_opt_mode(True)
args = [qemu_nbd, "-f", "qcow2", "-A", "-B", "bitmap0", "-B", "bitmap1",
        "'"$file"'"]
h.connect_systemd_socket_activation(args)
assert h.aio_is_negotiating() is True
assert h.get_extended_headers_negotiated() is False

# Flag not available until info or go
try:
  h.can_block_status_payload()
  assert False
except nbd.Error:
  pass
h.opt_info()
assert h.can_block_status_payload() is False
assert h.can_meta_context("base:allocation") is True

# Filter request not allowed if not advertised
def f():
  assert False
h.opt_go()
assert h.can_block_status_payload() is False
try:
  h.block_status_filter(0, 512, ["base:allocation"], f)
  assert False
except nbd.Error:
  pass
h.shutdown()
'

# Conditional part of test: only run if qemu is new enough to advertise
# support for block status payload.
requires nbdinfo --can block-status-payload -- [ $QEMU_NBD -r -f qcow2 "$file" ]
$VG ./block-status-payload \
    $QEMU_NBD -f qcow2 -A -B bitmap0 -B bitmap1 "$file"
