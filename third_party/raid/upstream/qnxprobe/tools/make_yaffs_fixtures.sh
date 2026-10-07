#!/usr/bin/env bash
# Build tests/fixtures/yaffs*-*.img.gz and the lists the self-test checks them
# against.
#
# Runs on Linux with a C compiler and no root. The writers are Aleph One's own
# image makers from the yaffs2 tree (github.com/Aleph-One-Ltd/yaffs2, commit
# 474b3acb927d27b2305618aaf24456b9d33fe91b), built here from source: pass the
# tree's path as $YAFFS2 (default ~/flashfs-kit/yaffs2).
#
#   yaffs2-le    mkyaffs2image: 2048-byte pages, 64-byte spare, packed tags
#                with their ECC at spare offset 0
#   yaffs2-be    mkyaffs2image ... convert: the same, big endian
#   yaffs2-oob2  yaffs2-le with every spare shifted two bytes on, where a NAND
#                controller's free OOB bytes start after the bad-block marker
#                (the page data is untouched)
#   yaffs1       mkyaffsimage: 512-byte pages, 16-byte YAFFS1 spare
#
# Oracles, independent of the reader under test:
#
#   yaffs.src.sha256   sha256sum over the source tree
#   yaffs.src.stat     every entry's octal mode, size and mtime (directory
#                      sizes are not compared: YAFFS records none)
#
# The upstream utils do not build as shipped at that commit (YTIME_T and u64
# are only defined for the "direct" build); both are defined on the compile
# line, and neither touches the on-flash layout.
set -euo pipefail

out=${1:-$(cd "$(dirname "$0")/.." && pwd)/tests/fixtures}
YAFFS2=${YAFFS2:-$HOME/flashfs-kit/yaffs2}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

( cd "$YAFFS2/utils"
  cp ../core/yaffs_ecc.c ../core/yaffs_packedtags2.c ../direct/yaffs_hweight.c .
  flags=(-I. -I../core -I../direct -DCONFIG_YAFFS_UTIL -DYTIME_T=u32 "-Du64=unsigned long long" -O2)
  gcc "${flags[@]}" -o "$work/mkyaffs2image" mkyaffs2image.c yaffs_packedtags2.c yaffs_ecc.c yaffs_hweight.c
  gcc "${flags[@]}" -o "$work/mkyaffsimage" mkyaffsimage.c yaffs_ecc.c yaffs_hweight.c )

src=$work/src
mkdir -p "$src/dir/sub/deeper" "$src/empty_dir" "$src/manyfiles"
python3 - "$src" <<'PY'
import os, random, sys
root = sys.argv[1]
rnd = random.Random(2026)
def blob(n): return bytes(rnd.getrandbits(8) for _ in range(n))
def text(n, tag):
    line = (tag + " yaffs fixture line\n").encode()
    return (line * (n // len(line) + 1))[:n]
open(f"{root}/small.txt", "wb").write(b"a file shorter than one page\n")
open(f"{root}/empty.bin", "wb").write(b"")
open(f"{root}/page.txt", "wb").write(text(2048, "page"))
open(f"{root}/dir/many_pages.txt", "wb").write(text(30 * 2048 + 999, "pages"))
open(f"{root}/dir/random.bin", "wb").write(blob(5000))
open(f"{root}/dir/sub/deeper/deep.txt", "wb").write(b"deep file\n")
for i in range(150):
    open(f"{root}/manyfiles/entry_{i:04d}.txt", "wb").write(b"m%04d\n" % i)
open(f"{root}/" + "L" * 251 + ".txt", "wb").write(b"a name 255 bytes long\n")
os.symlink("dir/many_pages.txt", f"{root}/link_to_pages")
os.link(f"{root}/small.txt", f"{root}/dir/hardlink_to_small.txt")
PY
find "$src" -exec touch -h -d '2024-05-06 07:08:09 UTC' {} +
touch -d '2023-01-02 03:04:05 UTC' "$src/dir/many_pages.txt"

( cd "$src" && find . -type f -print0 | sort -z | xargs -0 sha256sum | sed 's|  \./|  |' ) \
    > "$out/yaffs.src.sha256"
python3 - "$src" > "$out/yaffs.src.stat" <<'PY'
import os, sys
root = sys.argv[1]
for dirpath, dirs, files in os.walk(root):
    for name in sorted(dirs + files):
        full = os.path.join(dirpath, name)
        st = os.lstat(full)
        print(f"{st.st_mode:o} {st.st_size} {int(st.st_mtime)} {os.path.relpath(full, root)}")
PY

"$work/mkyaffs2image" "$src" "$work/yaffs2-le.img" >/dev/null
"$work/mkyaffs2image" "$src" "$work/yaffs2-be.img" convert >/dev/null
"$work/mkyaffsimage" "$src" "$work/yaffs1.img" >/dev/null
python3 - "$work/yaffs2-le.img" "$work/yaffs2-oob2.img" <<'PY'
import sys
src, dst = sys.argv[1], sys.argv[2]
data = open(src, "rb").read()
page, chunk = 2112, 2048
out = bytearray()
for at in range(0, len(data), page):
    out += data[at:at + chunk]
    spare = data[at + chunk:at + page]
    out += b"\xff\xff" + spare[:-2]
open(dst, "wb").write(bytes(out))
PY

for f in yaffs2-le yaffs2-be yaffs2-oob2 yaffs1; do
    gzip -9 -n -c "$work/$f.img" > "$out/$f.img.gz"
    printf '%-12s %9d bytes, %7d gzipped\n' "$f" "$(stat -c%s "$work/$f.img")" \
        "$(stat -c%s "$out/$f.img.gz")"
done
