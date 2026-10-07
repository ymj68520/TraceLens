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

# Check that code which uses assert(3) includes <assert.h>

source ./functions.sh
set -e

# Check we're running from the git checkout and have git grep.
requires test -d "$abs_top_srcdir/.git"
requires git --version
requires git grep --help
requires grep --version

cd $abs_top_srcdir

fail=0

for f in $( git ls-files '*.[ch]' | grep -v generator/states ); do
    wc="$( < $f grep -E '\bassert.?\(' | wc -l )"
    if [ "$wc" -ge 1 ]; then
        if ! grep -sqF "<assert.h>" $f; then
            echo "$f uses assert(3) but does not include <assert.h>"
            fail=1
        fi
    fi
done

exit $fail
