#!/usr/bin/env bash
# Build tests/fixtures/f2fs-fixture-free.img.gz and f2fs-fixture.free.sha256.
#
# MUST RUN AS ROOT on Linux (it mounts a loop device). Two things no other
# fixture has, and both need the kernel driver to write the volume TWICE:
#
#   1. A set bit in the checkpoint's NAT version bitmap. The first checkpoint
#      after mkfs leaves every NAT block on its first copy, so a fixture written
#      once (sload, or one mount) cannot tell a reader that picks the copy with
#      the wrong bit order from one that picks it right: both read copy one.
#      A second mount session rewrites NAT block 0 and the bitmap flips to 0x80.
#      Measured: the 1.28 reader, which read that bitmap little-endian, finds
#      zero files on this volume; the kernel reads 44.
#   2. A deleted file whose bytes are still in free space. marker.bin is written
#      in the first session, 1 MiB of blocks that each name their own index, and
#      deleted in the second; mounted nodiscard, so the loop device does not
#      zero the freed blocks. free_extents must report every one of its blocks.
#
# The kernel is the oracle for the surviving files (a read-only remount and
# sha256sum); the marker's presence in the image and in the reported runs is
# checked by the self-test directly. fsck runs on a copy, since it rewrites.
#
#   sudo SBIN=/path/to/f2fs-tools/sbin bash tools/make_f2fs_free_fixture.sh [outdir]
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root (it mounts a loop device)" >&2; exit 1; }
SBIN=${SBIN:-}
tool() { if [ -n "$SBIN" ]; then "$SBIN/$1" "${@:2}"; else "$@"; fi; }
out=${1:-$(cd "$(dirname "$0")/.." && pwd)/tests/fixtures}
owner=${SUDO_USER:-root}
work=$(mktemp -d)
trap 'umount "$work/mnt" 2>/dev/null || true; rm -rf "$work"' EXIT
mkdir -p "$work/mnt"

truncate -s 128M "$work/f2fs.img"
tool mkfs.f2fs -f -q -O extra_attr,inode_checksum,flexible_inline_xattr,inode_crtime,sb_checksum,lost_found \
    "$work/f2fs.img" </dev/null
modprobe f2fs 2>/dev/null || true

# session 1: the marker (deleted later), a kept file, a holey file, an inline one
mount -o loop,nodiscard "$work/f2fs.img" "$work/mnt"
python3 - "$work/mnt" <<'PY'
import sys, random
m = sys.argv[1]; rnd = random.Random(11)
def blob(n): return bytes(rnd.getrandbits(8) for _ in range(n))
with open(f"{m}/marker.bin", "wb") as f:
    for i in range(256):                                   # 1 MiB, each block self-identifying
        f.write(b"F2FS-FREE-MARKER-%04d-" % i + bytes(4096 - 22))
open(f"{m}/keep1.bin", "wb").write(blob(300000))
with open(f"{m}/holey.bin", "wb") as f:
    f.seek(2 * 1024 * 1024); f.write(blob(8192)); f.truncate(4 * 1024 * 1024)
open(f"{m}/tiny.txt", "wb").write(b"inline\n")
PY
sync; umount "$work/mnt"

# session 2: delete the marker and write more, so NAT and SIT blocks are rewritten
mount -o loop,nodiscard "$work/f2fs.img" "$work/mnt"
rm "$work/mnt/marker.bin"
python3 - "$work/mnt" <<'PY'
import os, sys, random
m = sys.argv[1]; rnd = random.Random(12)
def blob(n): return bytes(rnd.getrandbits(8) for _ in range(n))
os.mkdir(f"{m}/later")
for i in range(40):
    open(f"{m}/later/f{i:03d}.bin", "wb").write(blob(5000 + i))
open(f"{m}/keep2.bin", "wb").write(blob(200000))
PY
sync; umount "$work/mnt"

# the kernel reads every surviving file back
mount -o loop,ro "$work/f2fs.img" "$work/mnt"
( cd "$work/mnt" && find . -type f -exec sha256sum {} \; | sed 's|  \./|  |' | sort ) \
    > "$out/f2fs-fixture.free.sha256"
umount "$work/mnt"
gzip -9 -c "$work/f2fs.img" > "$out/f2fs-fixture-free.img.gz"
cp "$work/f2fs.img" "$work/fsck-copy.img"
tool fsck.f2fs "$work/fsck-copy.img" </dev/null 2>&1 | grep -iE "valid_block|SIT valid|Unreach|corrupt" || true
chown "$owner" "$out/f2fs-fixture.free.sha256" "$out/f2fs-fixture-free.img.gz"
echo "wrote:"
ls -la "$out/f2fs-fixture-free.img.gz" "$out/f2fs-fixture.free.sha256"
echo "files the kernel read: $(wc -l < "$out/f2fs-fixture.free.sha256")"
