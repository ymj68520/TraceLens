#!/usr/bin/env bash
# Build tests/fixtures/squashfs-*.img.gz and the lists the self-test checks them
# against.
#
# Runs on Linux with squashfs-tools installed (no root, no mount). One source
# tree is packed once per compressor mksquashfs offers, plus an image with no
# compression at all and one with 4 KiB blocks, so every decompressor and both
# the compressed and stored paths are exercised by the same files.
#
# Two oracles, both independent of the reader under test:
#
#   squashfs.src.sha256   sha256sum over the source tree, one line per regular
#                         file. mksquashfs stores file bytes exactly, so the
#                         source is the truth for every image.
#
#   squashfs.lln          unsquashfs -lln of the gzip image: every entry's
#                         numeric mode, owner, size, mtime and path, as the
#                         squashfs-tools reader sees it. The self-test compares
#                         the type, permission bits, size and mtime of every
#                         entry against it. (Its paths start "squashfs-root".)
#
# Before anything is written, every image is extracted with unsquashfs and its
# files hashed against the source list, so a fixture that squashfs-tools itself
# cannot read back never reaches the repository.
#
# The tree is chosen for its shapes: files that live only in a fragment, a file
# of exactly two blocks (no fragment), a multi-block file with a fragment tail,
# a file with holes (mksquashfs stores an all-zero block as length 0), a file
# shaped to force an LZ compressor's far and 2..3 KiB matches, a file of
# random bytes (in the 4 KiB-block image its blocks do not compress and are
# stored with bit 24 set), two
# identical files (stored once), a hard link, an empty file, an empty and a
# nested directory, an extended attribute, a directory of 600 entries (more than one directory header
# and more than one metadata block), a 255-byte name, a symlink, and a FIFO and
# a character device made through mksquashfs pseudo definitions.
set -euo pipefail

out=${1:-$(cd "$(dirname "$0")/.." && pwd)/tests/fixtures}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
src=$work/src
mkdir -p "$src/dir/sub/deeper" "$src/empty_dir" "$src/manyfiles"

python3 - "$src" <<'PY'
import os, random, struct, sys
root = sys.argv[1]
rnd = random.Random(2026)
def blob(n): return bytes(rnd.getrandbits(8) for _ in range(n))
def text(n, tag):
    line = (tag + " squashfs fixture line\n").encode()
    return (line * (n // len(line) + 1))[:n]
open(f"{root}/small.txt", "wb").write(b"a file small enough to live in a fragment\n")
open(f"{root}/empty.bin", "wb").write(b"")
open(f"{root}/two_blocks.txt", "wb").write(text(2 * 131072, "exact"))
open(f"{root}/dir/tail.txt", "wb").write(text(3 * 131072 + 5000, "tail"))
open(f"{root}/dir/random.bin", "wb").write(blob(10000))
open(f"{root}/dir/sub/deeper/deep.txt", "wb").write(b"deep file\n")
# Shapes an LZ compressor can only encode with its rarer instructions, all
# inside the first 128 KiB block: a random 2,000-byte run repeated 18,000
# bytes of text later (a far match, longer than the short length field
# holds), then random bytes where every 40th position repeats the 3 bytes
# found 2,500 bytes earlier (short matches from 2..3 KiB back, each between
# literals).
a = blob(2000)
shapes = bytearray(a + text(18000, "filler") + a)
for i in range(12000):
    shapes.append(shapes[-2500] if i % 40 < 3 and i >= 2500 else rnd.getrandbits(8))
open(f"{root}/dir/lz_shapes.bin", "wb").write(bytes(shapes))
open(f"{root}/dup_a.txt", "wb").write(text(40000, "duplicate"))
open(f"{root}/dup_b.txt", "wb").write(text(40000, "duplicate"))
# Holes: two leading blocks of zeros, data, two more zero blocks, a short tail.
with open(f"{root}/dir/holes.bin", "wb") as f:
    f.write(bytes(2 * 131072))
    f.write(text(131072, "middle"))
    f.write(bytes(2 * 131072))
    f.write(b"end of the file with holes\n")
for i in range(600):
    open(f"{root}/manyfiles/entry_{i:04d}_with_a_longer_name.txt", "wb").write(b"m%04d\n" % i)
open(f"{root}/" + "L" * 251 + ".txt", "wb").write(b"a name 255 bytes long\n")
os.symlink("dir/tail.txt", f"{root}/link_to_tail")
os.link(f"{root}/small.txt", f"{root}/dir/hardlink_to_small.txt")
PY

# Fixed times, so the listing oracle is reproducible.
find "$src" -exec touch -h -d '2024-05-06 07:08:09 UTC' {} +
touch -d '2023-01-02 03:04:05 UTC' "$src/dir/tail.txt"

( cd "$src" && find . -type f -print0 | sort -z | xargs -0 sha256sum | sed 's|  \./|  |' ) \
    > "$work/squashfs.src.sha256"

# Pseudo entries take the build time unless given one (the upper-case types).
pseudo=(-p "dev_null C 1714979289 666 0 0 1 3" -p "a_fifo I 1714979289 644 0 0 f"
        -p "dup_a.txt x user.note=an extended attribute")
common=(-noappend -quiet -no-progress -all-root -mkfs-time 1700000000 "${pseudo[@]}")

build() {   # build <name> <mksquashfs options...>
    local name=$1; shift
    mksquashfs "$src" "$work/$name.img" "${common[@]}" "$@" >/dev/null
    rm -rf "$work/x"
    unsquashfs -q -n -d "$work/x" "$work/$name.img" >/dev/null 2>&1 || true
    ( cd "$work/x" && find . -type f -print0 | sort -z | xargs -0 sha256sum | sed 's|  \./|  |' ) \
        > "$work/$name.check"
    if ! diff -q "$work/squashfs.src.sha256" "$work/$name.check" >/dev/null; then
        echo "unsquashfs does not read $name back as the source tree" >&2
        diff "$work/squashfs.src.sha256" "$work/$name.check" | head >&2
        exit 1
    fi
    gzip -9 -n -c "$work/$name.img" > "$out/squashfs-$name.img.gz"
    printf '%-10s %8d bytes, %7d gzipped\n' "$name" "$(stat -c%s "$work/$name.img")" \
        "$(stat -c%s "$out/squashfs-$name.img.gz")"
}

build gzip
build xz    -comp xz -Xbcj arm
build lzma  -comp lzma
build lzo   -comp lzo
build lz4   -comp lz4 -Xhc
build zstd  -comp zstd
build none  -noI -noId -noD -noF -noX
build small -b 4096 -comp gzip

cp "$work/squashfs.src.sha256" "$out/squashfs.src.sha256"
TZ=UTC unsquashfs -lln "$work/gzip.img" | LC_ALL=C sort -k6 > "$out/squashfs.lln"
echo "wrote $(ls "$out"/squashfs-* | wc -l) images, $(wc -l < "$out/squashfs.src.sha256") hashed files, $(wc -l < "$out/squashfs.lln") listed entries"
