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

import nbd

a = 0
b = 0


def set_a(i):
    global a
    a = i


def set_b(i):
    global b
    b = i


h1 = nbd.NBD()
h2 = nbd.NBD()

h1.add_close_callback(lambda: set_a(1))
h1.add_close_callback(lambda: set_b(2))
h2.add_close_callback(lambda: set_a(2))

assert a == 0
assert b == 0

h1.close()
assert a == 1
assert b == 2

h2.close()
assert a == 2
assert b == 2
