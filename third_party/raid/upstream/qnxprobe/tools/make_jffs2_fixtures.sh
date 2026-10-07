#!/usr/bin/env bash
# Build tests/fixtures/jffs2-*.img.gz and the lists the self-test checks them
# against.
#
# Runs on Linux with mtd-utils installed (no root, no mount). One source tree is
# written by mkfs.jffs2 several ways, so the byte orders, the compressors and
# the node kinds a reader meets are all exercised by the same files:
#
#   le-zlib   little endian, the default compressor priority (zlib, then rtime)
#   be-zlib   the same tree, big endian
#   le-lzo    LZO forced for every node that shrinks
#   le-rtime  zlib disabled, so rtime is used wherever it shrinks a node
#   le-none   no compression at all
#   le-sum    le-zlib run through sumtool, so every erase block ends in an
#             erase block summary node a reader must step over
#
# Two oracles, both independent of the reader under test:
#
#   jffs2.src.sha256   sha256sum over the source tree, one line per regular
#                      file; mkfs.jffs2 stores file bytes exactly.
#   jffs2.src.stat     every entry's octal mode, size and mtime, read from the
#                      source tree with stat (a symlink's size is its target's
#                      length; a device's is 0). Directory sizes are not
#                      compared: JFFS2 records none.
#
# mkfs.jffs2 records each file's own mtime. Device nodes come from a devtable
# (-D), which is how mkfs.jffs2 makes them without root; they are checked against
# the devtable itself, which is their oracle for type and permissions.
# mkfs.jffs2 stamps them, and so the directory holding them, with the time it
# ran, and has no option to fix that time other than --faketime, which zeroes
# every time in the image; so /dev's time is not in jffs2.src.stat's promise.
set -euo pipefail

out=${1:-$(cd "$(dirname "$0")/.." && pwd)/tests/fixtures}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
src=$work/src
mkdir -p "$src/dir/sub/deeper" "$src/empty_dir" "$src/manyfiles" "$src/dev"

python3 - "$src" <<'PY'
import os, random, struct, sys
root = sys.argv[1]
rnd = random.Random(2026)
def blob(n): return bytes(rnd.getrandbits(8) for _ in range(n))
def text(n, tag):
    line = (tag + " jffs2 fixture line\n").encode()
    return (line * (n // len(line) + 1))[:n]
open(f"{root}/small.txt", "wb").write(b"a file small enough for one node\n")
open(f"{root}/empty.bin", "wb").write(b"")
open(f"{root}/page.txt", "wb").write(text(4096, "page"))
open(f"{root}/dir/many_nodes.txt", "wb").write(text(10 * 4096 + 777, "nodes"))
open(f"{root}/dir/random.bin", "wb").write(blob(9000))
open(f"{root}/dir/sub/deeper/deep.txt", "wb").write(b"deep file\n")
# A file with pages of zeros between data: mkfs.jffs2 may write those as holes.
with open(f"{root}/dir/holes.bin", "wb") as f:
    f.write(bytes(3 * 4096)); f.write(text(4096, "middle")); f.write(bytes(2 * 4096))
    f.write(b"end of the file with holes\n")
# Shapes that only an LZ compressor's rarer instructions encode, all inside
# one 4 KiB node: a 400-byte random run repeated after text, then random bytes
# where every 40th position repeats the 3 bytes 2,500 bytes back.
a = blob(400)
shapes = bytearray(a + text(1200, "filler") + a)
while len(shapes) < 4096:
    i = len(shapes)
    shapes.append(shapes[-2500] if i % 40 < 3 and i >= 2500 else rnd.getrandbits(8))
open(f"{root}/dir/lz_shapes.bin", "wb").write(bytes(shapes))
for i in range(300):
    open(f"{root}/manyfiles/entry_{i:04d}.txt", "wb").write(b"m%04d\n" % i)
open(f"{root}/" + "L" * 250 + ".txt", "wb").write(b"a name 254 bytes long, the JFFS2 maximum\n")
os.symlink("dir/many_nodes.txt", f"{root}/link_to_nodes")
os.link(f"{root}/small.txt", f"{root}/dir/hardlink_to_small.txt")
PY

find "$src" -exec touch -h -d '2024-05-06 07:08:09 UTC' {} +
touch -d '2023-01-02 03:04:05 UTC' "$src/dir/many_nodes.txt"

cat > "$work/devtable" <<'EOF'
# name          type mode uid gid major minor start inc count
/dev/null       c    666  0   0   1     3     0     0   -
/dev/sda        b    660  0   6   8     0     0     0   -
EOF

( cd "$src" && find . -type f -print0 | sort -z | xargs -0 sha256sum | sed 's|  \./|  |' ) \
    > "$work/jffs2.src.sha256"
python3 - "$src" > "$work/jffs2.src.stat" <<'PY'
import os, sys
root = sys.argv[1]
for dirpath, dirs, files in os.walk(root):
    for name in sorted(dirs + files):
        full = os.path.join(dirpath, name)
        st = os.lstat(full)
        print(f"{st.st_mode:o} {st.st_size} {int(st.st_mtime)} {os.path.relpath(full, root)}")
PY

build() {   # build <name> <mkfs.jffs2 options...>
    local name=$1; shift
    mkfs.jffs2 -r "$src" -o "$work/$name.img" -e 64KiB -D "$work/devtable" "$@"
    gzip -9 -n -c "$work/$name.img" > "$out/jffs2-$name.img.gz"
    printf '%-8s %8d bytes, %7d gzipped\n' "$name" "$(stat -c%s "$work/$name.img")" \
        "$(stat -c%s "$out/jffs2-$name.img.gz")"
}

build le-zlib -l
build be-zlib -b
build le-lzo  -l -X lzo -x zlib -x rtime
build le-rtime -l -x zlib
build le-none -l -m none
sumtool -i "$work/le-zlib.img" -o "$work/le-sum.img" -e 64KiB -l
gzip -9 -n -c "$work/le-sum.img" > "$out/jffs2-le-sum.img.gz"
printf '%-8s %8d bytes, %7d gzipped\n' le-sum "$(stat -c%s "$work/le-sum.img")" \
    "$(stat -c%s "$out/jffs2-le-sum.img.gz")"

cp "$work/devtable" "$out/jffs2.devtable"
cp "$work/jffs2.src.sha256" "$out/jffs2.src.sha256"
cp "$work/jffs2.src.stat" "$out/jffs2.src.stat"
echo "wrote $(ls "$out"/jffs2-*.img.gz | wc -l) images, $(wc -l < "$out/jffs2.src.sha256") hashed files, $(wc -l < "$out/jffs2.src.stat") stat lines"
