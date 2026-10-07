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

include $(top_srcdir)/subdir-rules.mk

EXTRA_DIST = \
	README \
	nbdsh \
	$(NULL)

if HAVE_BASH_COMPLETION

bashcomp_DATA = nbddump nbdsh

if HAVE_LIBXML2
bashcomp_DATA += nbdcopy nbdinfo
endif HAVE_LIBXML2

if HAVE_FUSE
bashcomp_DATA += nbdfuse
endif

if HAVE_PYTHON
bashcomp_DATA += nbddiscard nbdzero
endif

if HAVE_UBLK
bashcomp_DATA += nbdublk
endif

nbdcopy: nbdsh
	rm -f $@
	$(LN_S) $(srcdir)/nbdsh $@

nbddiscard: nbdsh
	rm -f $@
	$(LN_S) $(srcdir)/nbdsh $@

nbddump: nbdsh
	rm -f $@
	$(LN_S) $(srcdir)/nbdsh $@

nbdfuse: nbdsh
	rm -f $@
	$(LN_S) $(srcdir)/nbdsh $@

nbdinfo: nbdsh
	rm -f $@
	$(LN_S) $(srcdir)/nbdsh $@

nbdublk: nbdsh
	rm -f $@
	$(LN_S) $(srcdir)/nbdsh $@

nbdzero: nbdsh
	rm -f $@
	$(LN_S) $(srcdir)/nbdsh $@

CLEANFILES += nbdcopy nbddiscard nbddump nbdfuse nbdinfo nbdublk nbdzero

endif
