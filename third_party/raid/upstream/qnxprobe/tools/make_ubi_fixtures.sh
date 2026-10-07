#!/usr/bin/env bash
# Build tests/fixtures/ubi-*.img.gz and ubifs-*.img.gz and the lists the
# self-test checks them against.
#
# Runs on Linux with mtd-utils and squashfs-tools installed (no root, no
# mount). mkfs.ubifs writes a UBIFS volume from a source tree with everything
# committed to its index; ubinize wraps volumes into a UBI image as a NAND or
# NOR programmer would write it. Images:
#
#   ubifs-lzo      a bare mkfs.ubifs image (no UBI), LZO, the default
#   ubi-nand-lzo   UBI for 2 KiB-page, 128 KiB-block NAND, three volumes:
#                    "rootfs_data"  dynamic, UBIFS (LZO) from the source tree
#                    "rootfs"       static, a SquashFS of the tree's dir/
#                    "kernel"       static, 150,000 bytes of raw data (two LEBs)
#   ubi-nand-zlib  the same UBIFS volume compressed with zlib
#   ubi-nand-zstd  and with zstd
#   ubi-nand-none  and uncompressed
#   ubi-nor        UBI for 64 KiB-block NOR flash (1-byte writes), UBIFS LZO
#
# Oracles, all independent of the reader under test:
#
#   ubifs.src.sha256   sha256sum over the source tree
#   ubifs.src.stat     every entry's octal mode, size and mtime from the
#                      source tree (directory sizes are not compared: UBIFS
#                      records its own)
#   ubi.rootfs.sha256  sha256sum over dir/, the tree the SquashFS volume holds
#   ubi.kernel.sha256  sha256 of the raw kernel volume's bytes
#
set -euo pipefail

out=${1:-$(cd "$(dirname "$0")/.." && pwd)/tests/fixtures}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
src=$work/src
mkdir -p "$src/dir/sub/deeper" "$src/empty_dir" "$src/manyfiles"

python3 - "$src" "$work/kernel.bin" <<'PY'
import os, random, sys
root, kernel = sys.argv[1], sys.argv[2]
rnd = random.Random(2026)
def blob(n): return bytes(rnd.getrandbits(8) for _ in range(n))
def text(n, tag):
    line = (tag + " ubifs fixture line\n").encode()
    return (line * (n // len(line) + 1))[:n]
open(f"{root}/small.txt", "wb").write(b"a file shorter than one UBIFS block\n")
open(f"{root}/empty.bin", "wb").write(b"")
open(f"{root}/block.txt", "wb").write(text(4096, "block"))
open(f"{root}/dir/many_blocks.txt", "wb").write(text(40 * 4096 + 1234, "blocks"))
open(f"{root}/dir/random.bin", "wb").write(blob(9000))
open(f"{root}/dir/sub/deeper/deep.txt", "wb").write(b"deep file\n")
# Blocks of zeros between data: mkfs.ubifs leaves an all-zero block out of the
# index, so the reader must supply the hole.
with open(f"{root}/dir/holes.bin", "wb") as f:
    f.write(bytes(3 * 4096)); f.write(text(4096, "middle")); f.write(bytes(2 * 4096))
    f.write(b"end of the file with holes\n")
a = blob(400)
shapes = bytearray(a + text(1200, "filler") + a)
while len(shapes) < 4096:
    i = len(shapes)
    shapes.append(shapes[-2500] if i % 40 < 3 and i >= 2500 else rnd.getrandbits(8))
open(f"{root}/dir/lz_shapes.bin", "wb").write(bytes(shapes))
for i in range(400):
    open(f"{root}/manyfiles/entry_{i:04d}_name.txt", "wb").write(b"m%04d\n" % i)
open(f"{root}/" + "L" * 251 + ".txt", "wb").write(b"a name 255 bytes long\n")
os.symlink("dir/many_blocks.txt", f"{root}/link_to_blocks")
os.link(f"{root}/small.txt", f"{root}/dir/hardlink_to_small.txt")
# The raw volume spans two NAND LEBs, so a static volume's last-LEB data size
# matters. Each 4 KiB block starts with its own index and is otherwise zeros:
# it compresses to almost nothing, yet a block read from the wrong LEB or
# offset carries the wrong index and fails the hash.
kblocks = b"".join((b"KERNEL-block-%08d\n" % i).ljust(4096, b"\0") for i in range(37))
open(kernel, "wb").write(kblocks[:150000])
PY

find "$src" -exec touch -h -d '2024-05-06 07:08:09 UTC' {} +
touch -d '2023-01-02 03:04:05 UTC' "$src/dir/many_blocks.txt"

( cd "$src" && find . -type f -print0 | sort -z | xargs -0 sha256sum | sed 's|  \./|  |' ) \
    > "$out/ubifs.src.sha256"
python3 - "$src" > "$out/ubifs.src.stat" <<'PY'
import os, sys
root = sys.argv[1]
for dirpath, dirs, files in os.walk(root):
    for name in sorted(dirs + files):
        full = os.path.join(dirpath, name)
        st = os.lstat(full)
        print(f"{st.st_mode:o} {st.st_size} {int(st.st_mtime)} {os.path.relpath(full, root)}")
PY
( cd "$src/dir" && find . -type f -print0 | sort -z | xargs -0 sha256sum | sed 's|  \./|  |' ) \
    > "$out/ubi.rootfs.sha256"
sha256sum "$work/kernel.bin" | sed "s|  .*|  kernel|" > "$out/ubi.kernel.sha256"

mksquashfs "$src/dir" "$work/rootfs.sqfs" -noappend -quiet -no-progress -all-root \
    -mkfs-time 1700000000 >/dev/null

nand=(-m 2048 -e 126976 -c 64)
mkfs.ubifs -r "$src" -o "$work/ubifs-lzo.img" "${nand[@]}" -x lzo
mkfs.ubifs -r "$src" -o "$work/ubifs-zlib.img" "${nand[@]}" -x zlib
mkfs.ubifs -r "$src" -o "$work/ubifs-zstd.img" "${nand[@]}" -x zstd
mkfs.ubifs -r "$src" -o "$work/ubifs-none.img" "${nand[@]}" -x none
mkfs.ubifs -r "$src" -o "$work/ubifs-nor.img" -m 1 -e 65408 -c 128 -x lzo

ubicfg() {   # ubicfg <ubifs image> <config file>
    cat > "$2" <<EOF
[rootfs_data]
mode=ubi
image=$1
vol_id=0
vol_type=dynamic
vol_name=rootfs_data
vol_size=4MiB

[rootfs]
mode=ubi
image=$work/rootfs.sqfs
vol_id=1
vol_type=static
vol_name=rootfs
vol_size=16KiB

[kernel]
mode=ubi
image=$work/kernel.bin
vol_id=2
vol_type=static
vol_name=kernel
vol_size=150000
EOF
}

for c in lzo zlib zstd none; do
    ubicfg "$work/ubifs-$c.img" "$work/$c.cfg"
    ubinize -o "$work/ubi-nand-$c.img" -p 128KiB -m 2048 -s 2048 "$work/$c.cfg"
done
ubicfg "$work/ubifs-nor.img" "$work/nor.cfg"
ubinize -o "$work/ubi-nor.img" -p 64KiB -m 1 "$work/nor.cfg"

for f in ubifs-lzo ubi-nand-lzo ubi-nand-zlib ubi-nand-zstd ubi-nand-none ubi-nor; do
    gzip -9 -n -c "$work/$f.img" > "$out/$f.img.gz"
    printf '%-14s %9d bytes, %7d gzipped\n' "$f" "$(stat -c%s "$work/$f.img")" \
        "$(stat -c%s "$out/$f.img.gz")"
done
