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
	nbddiscard \
	nbddiscard.pod \
	nbdzero.1 \
	test-discard-check.sh \
	test-discard-range.sh \
	test-discard.sh \
	test-help.sh \
	test-long-options.sh \
	test-short-options.sh \
	test-version.sh \
	test-zero-check.sh \
	test-zero-fast.sh \
	test-zero-range.sh \
	test-zero.sh \
	$(NULL)

if HAVE_PYTHON

bin_SCRIPTS = \
	nbddiscard \
	nbdzero \
	$(NULL)

nbdzero: nbddiscard
	rm -f $@
	$(LN_S) $< $@

if HAVE_POD

man_MANS = \
	nbddiscard.1 \
	nbdzero.1 \
	$(NULL)
CLEANFILES += nbddiscard.1

nbddiscard.1: nbddiscard.pod $(top_builddir)/podwrapper.pl
	$(PODWRAPPER) --section=1 --man $@ \
	    --html $(top_builddir)/html/$@.html \
	    $<

endif HAVE_POD

TESTS_ENVIRONMENT = \
	LIBNBD_DEBUG=1 \
	NBDKIT_DEBUG=1 \
	$(MALLOC_CHECKS) \
	EXPECTED_VERSION=$(VERSION) \
	$(NULL)
LOG_COMPILER = $(top_builddir)/run
TESTS = \
	test-help.sh \
	test-version.sh \
	test-short-options.sh \
	test-long-options.sh \
	$(NULL)

if HAVE_NBDKIT

TESTS += \
	test-discard.sh \
	test-discard-check.sh \
	test-discard-range.sh \
	test-zero.sh \
	test-zero-check.sh \
	test-zero-fast.sh \
	test-zero-range.sh \
	$(NULL)

endif HAVE_NBDKIT

endif HAVE_PYTHON
