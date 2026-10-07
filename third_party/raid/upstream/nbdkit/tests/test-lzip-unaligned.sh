#!/usr/bin/env bash
# nbdkit
# Copyright Jan Felix Langenbach
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

source ./functions.sh
set -e
set -x
set -u

requires_nbdcopy
requires_run
requires split --version
requires lzip --version
requires_filter lzip

d='lzip-unaligned.d'
cleanup_fn rm -rf $d
rm -rf $d
mkdir $d

input="$d/input.txt"
output="$d/output.txt"
parts="$d/input.txt.part"
archive="$d/archive.txt.lz"

cat > $input <<'EOF'
Lorem ipsum dolor sit amet, consectetur adipiscing elit. Suspendisse
consequat metus libero, luctus rhoncus nunc ullamcorper et. Integer
molestie interdum quam a tincidunt.
Aenean ornare rutrum viverra. Quisque sed purus lorem. Suspendisse
tempus finibus lorem id imperdiet. Fusce feugiat nulla libero, id
posuere nulla lobortis sed.
Integer dictum sapien a nunc aliquet, nec auctor risus sagittis.
Suspendisse porttitor porttitor molestie. Praesent ornare, dolor sed
volutpat consectetur, est metus iaculis magna, eu consequat purus
ipsum ac purus.
Praesent hendrerit, lorem convallis ullamcorper placerat, eros mi
blandit ligula, at egestas nunc nulla non mauris. Quisque ullamcorper
ligula ac condimentum blandit.
Quisque dictum lorem at massa mattis varius. Pellentesque at eros
hendrerit, fringilla velit vitae, lobortis lectus. Curabitur sagittis
risus eu placerat efficitur. In iaculis felis quis sapien dapibus, nec
porta ante aliquet.
Cras nec nunc eu metus congue cursus. In sit amet nisl non metus
elementum fringilla. Duis erat ligula, scelerisque molestie congue ut,
congue nec lacus.
EOF

split -l 1 $input $parts

for part in "$parts"*
do
    lzip --stdout "$part" >> $archive
done

lzip --list --verbose --verbose $archive

nbdkit file $archive --filter=lzip --run "nbdcopy -C 1 \$uri $output"
cmp $input $output
