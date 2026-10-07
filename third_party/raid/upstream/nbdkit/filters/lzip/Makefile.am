# nbdkit lzip filter
# Copyright Jan Felix Langenbach
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

include $(top_srcdir)/common-rules.mk

EXTRA_DIST = nbdkit-lzip-filter.pod

if HAVE_LZMA_LZIP_DECODER

filter_LTLIBRARIES = nbdkit-lzip-filter.la

# This filter shares some source files with nbdkit-xz-filter.  In
# RHEL 7 we cannot add the C files from ../xz directly to SOURCES
# because subdir-objects is broken.  Instead we create symlinks to
# them.
BUILT_SOURCES = \
	blkcache.c \
	$(NULL)
blkcache.c: $(srcdir)/../xz/blkcache.c
	ln -f -s $(srcdir)/../xz/$@
CLEANFILES += $(BUILT_SOURCES)

nbdkit_lzip_filter_la_SOURCES = \
	lzip.c \
	lzipfile.c \
	lzipfile.h \
	lzipindex.c \
	lzipindex.h \
	$(BUILT_SOURCES) \
	$(srcdir)/../xz/blkcache.h \
	$(top_srcdir)/include/nbdkit-filter.h \
	$(NULL)

nbdkit_lzip_filter_la_CPPFLAGS = \
	-I$(top_srcdir)/include \
	-I$(top_builddir)/include \
	-I$(top_srcdir)/filters/xz \
	-I$(top_srcdir)/common/include \
	-I$(top_srcdir)/common/utils \
	$(NULL)
nbdkit_lzip_filter_la_CFLAGS = \
	$(WARNINGS_CFLAGS) \
	$(LIBLZMA_CFLAGS) \
	$(NULL)
nbdkit_lzip_filter_la_LIBADD = \
	$(LIBLZMA_LIBS) \
	$(top_builddir)/common/utils/libutils.la \
	$(top_builddir)/common/replacements/libcompat.la \
	$(IMPORT_LIBRARY_ON_WINDOWS) \
	$(NULL)
nbdkit_lzip_filter_la_LDFLAGS = \
	-module -avoid-version -shared $(NO_UNDEFINED_ON_WINDOWS) \
	$(NULL)
if USE_LINKER_SCRIPT
nbdkit_lzip_filter_la_LDFLAGS += \
	-Wl,--version-script=$(top_srcdir)/filters/filters.syms
endif

if HAVE_POD

man_MANS = nbdkit-lzip-filter.1
CLEANFILES += $(man_MANS)

nbdkit-lzip-filter.1: nbdkit-lzip-filter.pod \
		$(top_builddir)/podwrapper.pl
	$(PODWRAPPER) --section=1 --man $@ \
		--html $(top_builddir)/html/$@.html \
		$<

endif HAVE_POD

endif HAVE_LZMA_LZIP_DECODER
