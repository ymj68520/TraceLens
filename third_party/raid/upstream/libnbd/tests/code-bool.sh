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

# Check that code which uses bool/true/false includes <stdbool.h>

source ./functions.sh
set -e

# Check we're running from the git checkout and have git grep.
requires test -d "$abs_top_srcdir/.git"
requires git --version
requires git grep --help
requires grep --version

cd $abs_top_srcdir

fail=0

for f in $( git ls-files '*.[ch]' |
            grep -v generator/states ); do
    wc="$( < $f grep -E '\b(bool|true|false)\b' |
                grep -Fv '/*' | grep -Ev '^ \*' | grep -Ev '"' | wc -l )"
    if [ "$wc" -ge 1 ]; then
        if ! grep -sqF "<stdbool.h>" $f; then
            echo "$f uses bool/true/false but does not include <stdbool.h>"
            fail=1
        fi
    fi
done

exit $fail
