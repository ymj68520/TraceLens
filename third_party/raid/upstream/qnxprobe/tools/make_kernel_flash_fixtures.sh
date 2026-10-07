#!/usr/bin/env bash
# Build tests/fixtures/{jffs2-nor,jffs2-nand,ubi-nand}-history.img.gz and the
# lists the self-test checks them against, with the Linux kernel's own JFFS2,
# UBI and UBIFS drivers writing the history and reading it back.
#
# Needs Linux, root (modprobe, mount) and mtd-utils. Run on kernel 7.0.0 with
# mtd-utils 2.3.0. Three images:
#
#   jffs2-nor-history   JFFS2 on NOR flash: block2mtd over a 4 MiB file with
#                       64 KiB eraseblocks. NOR is written in place, so JFFS2
#                       marks each node it supersedes obsolete on the flash.
#   jffs2-nand-history  JFFS2 on NAND: a 4 MiB nandsim partition (2 KiB pages,
#                       64-byte spare, 128 KiB eraseblocks), taken with
#                       nanddump --oob. NAND cannot be rewritten in place, so
#                       superseded nodes stay valid on the flash and only their
#                       version numbers say which is current.
#   ubi-nand-history    UBI on an 8 MiB nandsim partition, with a dynamic UBIFS
#                       volume (mounted with compr=lzo) and a static volume
#                       written twice with ubiupdatevol, taken with
#                       nanddump --oob while UBIFS is still mounted, so the
#                       history since the last commit is in the journal. The
#                       static volume's first version is put back into two free
#                       eraseblocks from a dump taken between the two writes,
#                       the state a power cut during the rewrite leaves.
#
# The history, the same on each: data overwritten in the middle and appended, a
# shrink then data written past the old end, a truncate that grows, a file
# written only far from its start, one file rewritten forty times, a deleted
# file and directory, a rename across directories, a rename over an existing
# name, a hard link whose first name is removed, a symlink, a permission
# change, and (where the filesystem supports it) a file created unnamed with
# O_TMPFILE, written, given an extended attribute and only then linked in.
# Before the history, more data is written and deleted than the volume holds,
# with a sync() after each file, so garbage collection runs and (on UBIFS, where
# sync() runs a commit) the index is built. After that every step is fsynced,
# so each reaches the flash before the next changes it, and nothing calls
# sync(), so on UBIFS the history stays in the journal.
#
# The oracle is the kernel reading each image back. The NOR image is copied and
# the copy mounted read-only; the JFFS2 NAND image is mounted read-only again
# and dumped a second time, which must equal the first; the UBI image is
# written back to an erased partition with nandwrite, attached and mounted
# read-only, and afterwards only the two stale eraseblocks may have changed
# (the kernel erases them as older copies). Every file the kernel reads is
# hashed (<name>.history.sha256), every entry's mode, size and mtime listed
# (<name>.history.stat), and the static volume hashed as the kernel reads it
# (ubi-nand.history.kernel.sha256), which must be its second version.
set -euo pipefail

[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
out=${1:-$(cd "$(dirname "$0")/.." && pwd)/tests/fixtures}
work=$(mktemp -d)
mnt=$work/mnt
mkdir -p "$mnt"
loop=""

cleanup() {
    set +e
    mountpoint -q "$mnt" && umount "$mnt"
    [ -e /dev/ubi0 ] && ubidetach -d 0 >/dev/null 2>&1
    modprobe -r block2mtd 2>/dev/null
    [ -n "$loop" ] && losetup -d "$loop" 2>/dev/null
    modprobe -r ubifs ubi nandsim 2>/dev/null
    rm -rf "$work"
}
trap cleanup EXIT

history() {   # history <mounted root> <churn blocks of 256 KiB>
    python3 - "$1" "$2" <<'PY'
import os, random, sys
root, churn = sys.argv[1], int(sys.argv[2])
rnd = random.Random(2026)
def text(n, tag):
    line = (tag + " kernel history line\n").encode()
    return (line * (n // len(line) + 1))[:n]
def p(*a):
    return os.path.join(root, *a)
def put(path, data, mode="wb", at=None):
    # Every write is fsynced, so each step reaches the flash before the next
    # one changes it: UBIFS otherwise holds data in the page cache, and data
    # overwritten or truncated there never reaches the flash at all.
    with open(path, mode) as f:
        if at is not None:
            f.seek(at)
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
def fsync(path):
    fd = os.open(path, os.O_RDONLY)
    os.fsync(fd)
    os.close(fd)
os.makedirs(p("dir", "sub"))
os.makedirs(p("gone_dir"))
# Each churn file is one random 4 KiB block repeated: the filesystem compresses
# every 4 KiB page on its own and cannot shrink it, while gzip, looking across
# pages, stores the leftovers in the committed image in very little space.
for i in range(churn):
    put(p("churn.bin"), rnd.randbytes(4096) * 64)
    os.sync()
    os.remove(p("churn.bin"))
os.sync()
put(p("keep.txt"), b"a file written once\n")
put(p("over.bin"), text(3 * 4096 + 100, "first"))
put(p("over.bin"), text(4096, "second"), "r+b", 4096)
put(p("over.bin"), text(5000, "appended"), "ab")
put(p("shrink.bin"), rnd.randbytes(20000))
os.truncate(p("shrink.bin"), 7000)
fsync(p("shrink.bin"))
put(p("shrink.bin"), text(500, "after the gap"), "r+b", 30000)
put(p("grow.bin"), text(1000, "grow"))
os.truncate(p("grow.bin"), 9000)
fsync(p("grow.bin"))
put(p("dir", "far.bin"), text(300, "far"), "wb", 50000)
for i in range(40):
    put(p("dir", "counter.txt"), b"version %d of this file\n" % i)
put(p("gone.txt"), text(3000, "deleted"))
os.remove(p("gone.txt"))
os.rmdir(p("gone_dir"))
put(p("old_name.txt"), text(700, "renamed"))
os.rename(p("old_name.txt"), p("dir", "sub", "new_name.txt"))
put(p("dir", "target.txt"), b"the file that gets replaced\n")
put(p("dir", "replacement.txt"), b"the file that replaced it\n")
os.rename(p("dir", "replacement.txt"), p("dir", "target.txt"))
put(p("first_name.txt"), text(2500, "linked"))
os.link(p("first_name.txt"), p("dir", "second_name.txt"))
os.remove(p("first_name.txt"))
os.symlink("dir/sub/new_name.txt", p("link_to_renamed"))
os.chmod(p("keep.txt"), 0o600)
try:
    fd = os.open(p("dir"), os.O_TMPFILE | os.O_WRONLY, 0o644)
except OSError as exc:
    print(f"  (no O_TMPFILE here: {exc.strerror})")
else:
    os.write(fd, text(1500, "tmpfile"))
    os.fsync(fd)        # its data reaches the flash while it has no name
    # and then its inode again, still with no link, after that data. UBIFS
    # never writes an unlinked inode on fsync (ubifs_write_inode skips
    # orphans), but setting an extended attribute is a journal update that
    # does. A replay that dropped the inode's data there would lose the
    # file's bytes; fs/ubifs/replay.c inode_still_linked is the rule that
    # keeps them.
    os.setxattr(fd, "user.qnxprobe", b"set while the file had no name")
    os.fsync(fd)
    os.link(f"/proc/self/fd/{fd}", p("dir", "was_tmpfile.bin"), follow_symlinks=True)
    os.close(fd)
put(p("last.txt"), b"written last\n")
# fsync every file and directory rather than sync(): on UBIFS sync() runs a
# commit (fs/ubifs/super.c ubifs_sync_fs), which would fold the history into
# the index, while fsync only flushes the write buffers, leaving it in the
# journal as it would be on a running device.
for dirpath, dirs, files in os.walk(root, topdown=False):
    for name in files:
        full = os.path.join(dirpath, name)
        if not os.path.islink(full):
            fd = os.open(full, os.O_RDONLY)
            os.fsync(fd)
            os.close(fd)
    fd = os.open(dirpath, os.O_RDONLY)
    os.fsync(fd)
    os.close(fd)
PY
}

readback() {   # readback <mounted root> <name>: the kernel's reading, as the oracle lists
    python3 - "$1" "$out/$2.history.sha256" "$out/$2.history.stat" <<'PY'
import hashlib, os, stat, sys
root, hashes, stats = sys.argv[1:4]
H, S = [], []
for dirpath, dirs, files in os.walk(root):
    for name in sorted(dirs + files):
        full = os.path.join(dirpath, name)
        rel = os.path.relpath(full, root)
        st = os.lstat(full)
        S.append(f"{st.st_mode:o} {st.st_size} {int(st.st_mtime)} {rel}")
        if stat.S_ISREG(st.st_mode):
            with open(full, "rb") as f:
                H.append(f"{hashlib.sha256(f.read()).hexdigest()}  {rel}")
open(hashes, "w").write("".join(l + "\n" for l in sorted(H, key=lambda l: l.split("  ", 1)[1])))
open(stats, "w").write("".join(l + "\n" for l in sorted(S, key=lambda l: l.split(" ", 3)[3])))
print(f"  kernel read back {len(H)} files, {len(S)} entries")
PY
}

mtdnum() { grep -F "\"$1" /proc/mtd | cut -d: -f1 | sed 's/^mtd//'; }

keep() {   # keep <file> <name>
    gzip -9 -n -c "$1" > "$out/$2-history.img.gz"
    printf '%s-history %d bytes, %d gzipped\n' "$2" "$(stat -c%s "$1")" \
        "$(stat -c%s "$out/$2-history.img.gz")"
}

modprobe -r ubifs ubi nandsim block2mtd 2>/dev/null || true

# -- JFFS2 on NOR ---------------------------------------------------------------
python3 -c "import sys; open(sys.argv[1], 'wb').write(b'\xff' * (4 << 20))" "$work/nor.img"
loop=$(losetup -f --show "$work/nor.img")
modprobe block2mtd block2mtd="$loop,64KiB"
n=$(mtdnum "block2mtd: $loop")
mount -t jffs2 "mtd$n" "$mnt"
history "$mnt" 32
umount "$mnt"
modprobe -r block2mtd
losetup -d "$loop"
cp "$work/nor.img" "$work/nor.ro"
loop=$(losetup -f --show "$work/nor.ro")
modprobe block2mtd block2mtd="$loop,64KiB"
n=$(mtdnum "block2mtd: $loop")
mount -t jffs2 -o ro "mtd$n" "$mnt"
readback "$mnt" jffs2-nor
umount "$mnt"
modprobe -r block2mtd
losetup -d "$loop"
loop=""
cmp -s "$work/nor.img" "$work/nor.ro" || { echo "the read-only mount changed the NOR image" >&2; exit 1; }
keep "$work/nor.img" jffs2-nor

# -- nandsim: 128 MiB, 2 KiB pages, 64-byte spare; partition 0 for UBI, 1 for JFFS2
modprobe nandsim id_bytes=0xec,0xa1,0x00,0x15 parts=64,32

# -- JFFS2 on NAND ---------------------------------------------------------------
flash_erase -q /dev/mtd1 0 0
mount -t jffs2 mtd1 "$mnt"
history "$mnt" 32
umount "$mnt"
nanddump -q --oob -f "$work/jffs2-nand.img" /dev/mtd1
mount -t jffs2 -o ro mtd1 "$mnt"
readback "$mnt" jffs2-nand
umount "$mnt"
nanddump -q --oob -f "$work/jffs2-nand.check" /dev/mtd1
cmp -s "$work/jffs2-nand.img" "$work/jffs2-nand.check" \
    || { echo "the read-only mount changed the JFFS2 NAND image" >&2; exit 1; }
keep "$work/jffs2-nand.img" jffs2-nand

# -- UBI and UBIFS on NAND ---------------------------------------------------------
# The static volume is written twice, first with version 1 of its data and then
# with version 2, and the flash is dumped in between. Rewriting a volume maps
# its blocks to new eraseblocks with higher sequence numbers and erases the old
# ones, so once the final image is taken, version 1's eraseblocks are put back
# into two eraseblocks that image holds free. That is the state a power cut
# during the rewrite leaves: two copies of each block, and only the sequence
# numbers say which is current. The kernel attaching the image is what decides.
python3 - "$work" <<'PY'
import sys
for v in (1, 2):
    blocks = b"".join((b"KERNEL-v%d-block-%08d\n" % (v, i)).ljust(4096, b"\0") for i in range(37))
    open(f"{sys.argv[1]}/kernel-v{v}.bin", "wb").write(blocks[:150000])
PY
modprobe ubi
modprobe ubifs
ubiformat -q -y /dev/mtd0
ubiattach -m 0 -d 0 >/dev/null
ubimkvol /dev/ubi0 -N rootfs_data -s 3MiB >/dev/null
ubimkvol /dev/ubi0 -N kernel -t static -s 256KiB >/dev/null
udevadm settle          # udev probes a new volume; an update needs it alone
ubiupdatevol /dev/ubi0_1 "$work/kernel-v1.bin"
ubidetach -d 0
nanddump -q --oob -f "$work/ubi-v1.img" /dev/mtd0
ubiattach -m 0 -d 0 >/dev/null
udevadm settle
ubiupdatevol /dev/ubi0_1 "$work/kernel-v2.bin"
# LZO rather than this kernel's default zstd, so the image is read on a Python
# without compression.zstd (the mkfs.ubifs fixtures cover zstd).
mount -t ubifs -o compr=lzo ubi0:rootfs_data "$mnt"
history "$mnt" 24
# Taken while mounted, after fsync: the journal since the last commit is on the
# flash and not yet in the index, as on a device imaged while it ran.
nanddump -q --oob -f "$work/ubi-v2.img" /dev/mtd0
umount "$mnt"
ubidetach -d 0
python3 - "$work/ubi-v1.img" "$work/ubi-v2.img" "$work/ubi-nand.img" > "$work/spliced" <<'PY'
import struct, sys
old, new = open(sys.argv[1], "rb").read(), bytearray(open(sys.argv[2], "rb").read())
page, spare, pages = 2048, 64, 64
peb = pages * (page + spare)
def vid(img, n):
    at = n * peb
    vid_off = struct.unpack_from(">I", img, at + 16)[0]   # the EC header's vid_hdr_offset
    return img[at + vid_off:at + vid_off + 64]
stale = [n for n in range(len(old) // peb) if vid(old, n)[:4] == b"UBI!"
         and struct.unpack_from(">I", vid(old, n), 8)[0] == 1]
free = [n for n in range(len(new) // peb) if new[n * peb:n * peb + 4] == b"UBI#"
        and vid(new, n) == b"\xff" * 64]
assert len(stale) == 2 and len(free) >= 2, (stale, free)
for src, dst in zip(stale, free[-2:]):
    new[dst * peb:(dst + 1) * peb] = old[src * peb:(src + 1) * peb]
    print(dst)
open(sys.argv[3], "wb").write(bytes(new))
PY
flash_erase -q /dev/mtd0 0 0
nandwrite -q --oob --noecc /dev/mtd0 "$work/ubi-nand.img"
ubiattach -m 0 -d 0 >/dev/null
udevadm settle
mount -t ubifs -o ro ubi0:rootfs_data "$mnt"
readback "$mnt" ubi-nand
umount "$mnt"
sha256sum < /dev/ubi0_1 | sed 's|  .*|  kernel|' > "$out/ubi-nand.history.kernel.sha256"
[ "$(cut -d' ' -f1 "$out/ubi-nand.history.kernel.sha256")" = "$(sha256sum < "$work/kernel-v2.bin" | cut -d' ' -f1)" ] \
    || { echo "the kernel did not read version 2 of the static volume" >&2; exit 1; }
echo "  kernel read version 2 of the static volume, with version 1 in eraseblocks $(tr '\n' ' ' < "$work/spliced")"
ubidetach -d 0
# Attaching schedules the stale copies for erasure; nothing else may change.
nanddump -q --oob -f "$work/ubi-nand.check" /dev/mtd0
python3 - "$work/ubi-nand.img" "$work/ubi-nand.check" "$work/spliced" <<'PY'
import sys
a, b = open(sys.argv[1], "rb").read(), open(sys.argv[2], "rb").read()
spliced = {int(x) for x in open(sys.argv[3]).read().split()}
peb = 64 * (2048 + 64)
changed = {n for n in range(len(a) // peb) if a[n * peb:(n + 1) * peb] != b[n * peb:(n + 1) * peb]}
if not changed <= spliced:
    sys.exit(f"attaching changed eraseblocks other than the stale copies: {sorted(changed - spliced)}")
print(f"  after the read, eraseblocks changed: {sorted(changed) or 'none'} (stale copies {sorted(spliced)})")
PY
keep "$work/ubi-nand.img" ubi-nand
