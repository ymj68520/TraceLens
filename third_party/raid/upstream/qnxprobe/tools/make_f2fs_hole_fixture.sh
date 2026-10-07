#!/usr/bin/env bash
# Build tests/fixtures/f2fs-fixture-holes.img.gz and f2fs-fixture.holes.sha256.
#
# MUST RUN AS ROOT on Linux (it mounts a loop device). sload.f2fs allocates every
# block, so it cannot produce a file with holes; the only way to get real
# unallocated blocks into an F2FS image is to let the kernel driver write sparse
# files. So this mounts a fresh volume, writes files with holes, unmounts cleanly,
# then reads every file back through a read-only kernel mount and records those
# hashes. The kernel is the oracle here, a reader independent of both qnxprobe and
# f2fs-tools; the self-test then requires this reader to reproduce those bytes,
# holes read as zeros.
#
#   sudo SBIN=/path/to/f2fs-tools/sbin bash tools/make_f2fs_hole_fixture.sh [outdir]
#
# SBIN is only needed if mkfs.f2fs is not on PATH.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root (it mounts a loop device)" >&2; exit 1; }
SBIN=${SBIN:-}
mkfs() { if [ -n "$SBIN" ]; then "$SBIN/mkfs.f2fs" "$@"; else mkfs.f2fs "$@"; fi; }
out=${1:-$(cd "$(dirname "$0")/.." && pwd)/tests/fixtures}
owner=${SUDO_USER:-root}
work=$(mktemp -d)
trap 'umount "$work/mnt" 2>/dev/null || true; rm -rf "$work"' EXIT
mkdir -p "$work/mnt"

truncate -s 128M "$work/f2fs.img"
mkfs -f -q -O extra_attr,inode_checksum,flexible_inline_xattr,inode_crtime,sb_checksum,lost_found \
    "$work/f2fs.img" </dev/null
modprobe f2fs 2>/dev/null || true
mount -o loop "$work/f2fs.img" "$work/mnt"
python3 - "$work/mnt" <<'PY'
import sys, random
m = sys.argv[1]; rnd = random.Random(7)
def blob(n): return bytes(rnd.getrandbits(8) for _ in range(n))
# leading hole, data at 1 MiB, middle hole, data at 5 MiB, trailing hole to 8 MiB
with open(f"{m}/holey.bin", "wb") as f:
    f.seek(1024 * 1024); f.write(blob(8192))
    f.seek(5 * 1024 * 1024); f.write(blob(4096))
    f.truncate(8 * 1024 * 1024)
open(f"{m}/allhole.bin", "wb").truncate(2 * 1024 * 1024)   # nothing but hole
open(f"{m}/normal.bin", "wb").write(blob(200000))          # fully written control
open(f"{m}/tiny.txt", "wb").write(b"inline\n")             # inline data
PY
sync
umount "$work/mnt"
mount -o loop,ro "$work/f2fs.img" "$work/mnt"
( cd "$work/mnt" && find . -type f -exec sha256sum {} \; | sed 's|  \./|  |' | sort ) \
    > "$out/f2fs-fixture.holes.sha256"
umount "$work/mnt"
gzip -9 -c "$work/f2fs.img" > "$out/f2fs-fixture-holes.img.gz"
chown "$owner" "$out/f2fs-fixture.holes.sha256" "$out/f2fs-fixture-holes.img.gz"
echo "wrote:"
ls -la "$out/f2fs-fixture-holes.img.gz" "$out/f2fs-fixture.holes.sha256"
cat "$out/f2fs-fixture.holes.sha256"
