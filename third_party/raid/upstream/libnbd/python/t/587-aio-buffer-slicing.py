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

# More tests of nbd.Buffer.  Slicing.

import nbd

buf = nbd.Buffer(512)
assert len(buf) == 512

buf[0:12] = b"hello, world"
assert buf[0] == 104   # 'h'
assert buf[11] == 100  # 'd'
assert buf[12] == 0

buf[12:27] = b"goodnight irene"
assert buf[0] == 104   # 'h'
assert buf[11] == 100  # 'd'
assert buf[12] == 103  # 'g'
assert buf[26] == 101  # 'e'

# Even though the buffer was uninitialized above, the first assignment
# should have initialized it:
for i in range(27, 511-27):
    assert buf[27+i] == 0
