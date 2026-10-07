# libnbd Python bindings
# Copyright Red Hat
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA

# More tests of nbd.Buffer.  Indexing.

import nbd

ba = bytearray(512)
buf = nbd.Buffer.from_bytearray(ba)
assert len(buf) == 512

assert buf[0] == 0
assert buf[511] == 0
buf[0] = 1
assert buf[0] == 1
assert buf[511] == 0

for i in range(0, 511):
    buf[i] = i & 255
assert buf[0] == 0
assert buf[1] == 1
assert buf[255] == 255
assert buf[256] == 0
for i in range(0, 511):
    assert buf[i] == i & 255

for i in range(0, 511):
    buf[i] = 0
assert buf.is_zero() is True

# Check that an uninitialized buffer reads as zero.  It should be
# initialized on the first read.
buf2 = nbd.Buffer(512)
for i in range(0, 511):
    assert buf2[i] == 0
