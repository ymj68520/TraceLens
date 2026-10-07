#!/usr/bin/env bash
# Build tests/fixtures/ext4-sparse.img.gz, ext2-sparse.img.gz and ext-sparse.sha256.
#
# Runs anywhere e2fsprogs is installed (Linux; no root, no mount: mke2fs -d writes
# the tree straight into the image and keeps each file's holes as holes). The hash
# list comes from sha256sum over the source tree, which is a reading of the bytes
# independent of the image and of any reader of it. The files are chosen for their
# shape: a hole first, a hole in the middle, a trailing hole past the last block, a
# file that is nothing but hole, a 3 MiB file with data at both ends only, plus a
# one-block file, a many-block file and a tiny one.
set -euo pipefail
out=${1:-$(cd "$(dirname "$0")/.." && pwd)/tests/fixtures}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/tree/dir"
python3 - "$work/tree" <<'PY'
import os, random, sys
os.chdir(sys.argv[1])
rnd = random.Random(11)
def blob(n): return bytes(rnd.getrandbits(8) for _ in range(n))
with open('all_hole.bin', 'wb') as f: f.truncate(4096)
with open('hole_middle.bin', 'wb') as f: f.write(blob(4096)); f.seek(20480); f.write(blob(4096))
with open('trailing_hole.bin', 'wb') as f: f.write(blob(4096)); f.truncate(4152)
with open('leading_hole.bin', 'wb') as f: f.seek(8192); f.write(blob(100))
with open('one_block.bin', 'wb') as f: f.write(blob(4096))
with open('dir/many_blocks.bin', 'wb') as f: f.write(blob(300 * 1024 + 17))
with open('dir/tiny.txt', 'wb') as f: f.write(b'tiny\n')
with open('dir/big_sparse.bin', 'wb') as f: f.write(blob(5000)); f.seek(3 * 1024 * 1024 - 3000); f.write(blob(3000))
PY
(cd "$work/tree" && find . -type f -print0 | sort -z | xargs -0 sha256sum | sed 's|  \./|  |') > "$out/ext-sparse.sha256"
mke2fs -q -t ext4 -L sparsefix -d "$work/tree" "$work/ext4-sparse.img" 24M
mke2fs -q -t ext2 -L sparsefix -d "$work/tree" "$work/ext2-sparse.img" 24M
gzip -9 -c "$work/ext4-sparse.img" > "$out/ext4-sparse.img.gz"
gzip -9 -c "$work/ext2-sparse.img" > "$out/ext2-sparse.img.gz"
ls -la "$out"/ext*-sparse.img.gz "$out/ext-sparse.sha256"
