#!/usr/bin/env bash
# Build tests/fixtures/f2fs-fixture.img.gz and the two hash lists the self-test
# checks it against.
#
# Runs on Linux with f2fs-tools installed (no root, no mount): mkfs.f2fs makes an
# empty image and sload.f2fs writes a source tree into it directly, the same way
# mke2fs -d and mkntfs do for the ext and NTFS fixtures. Nothing here reads the
# image with qnxprobe, so the hashes are independent of the reader under test.
#
# Two oracles, because sload.f2fs does not treat every file the same:
#
#   f2fs-fixture.src.sha256   sha256sum over the source tree, for every file that
#                             lives inside the inode's own address list (inline
#                             data, inline directories, files up to a few MiB) plus
#                             the multi-block directory. sload writes these
#                             byte-for-byte, so the source hash is the truth.
#
#   f2fs-fixture.nodes.sha256 for the one file large enough to run past the inode
#                             into direct and single-indirect node blocks. sload
#                             relocates such a file's node blocks (it writes them as
#                             if the inode carried no inline xattr while stamping the
#                             inode with one), so the source hash does not match.
#                             The recorded hash is what f2fs-tools' own dump.f2fs, an
#                             independent reader, extracts from the finished image.
#
# The files are chosen for their shape: a file kept inline in the inode, a one-block
# file and a hundred-block file addressed by the inode's own pointers, a 16 MiB file
# that crosses both direct nodes and reaches a single-indirect node, nested and empty
# directories, a directory of 600 files that cannot stay inline, and a symlink.
set -euo pipefail

SBIN=${SBIN:-}                       # dir holding mkfs.f2fs/sload.f2fs/dump.f2fs, if not on PATH
run() { if [ -n "$SBIN" ]; then "$SBIN/$1" "${@:2}"; else "$@"; fi; }
out=${1:-$(cd "$(dirname "$0")/.." && pwd)/tests/fixtures}
INLINE_MAX=$((3 * 1024 * 1024))      # a file at or under this stays inside the inode
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/src/dir/sub" "$work/src/empty_dir" "$work/src/manyfiles"

python3 - "$work/src" <<'PY'
import os, random, struct, sys
root = sys.argv[1]
rnd = random.Random(2026)
def blob(n): return bytes(rnd.getrandbits(8) for _ in range(n))
open(f"{root}/inline_small.txt", "wb").write(b"inline f2fs data, stays in the inode\n")
open(f"{root}/one_block.bin", "wb").write(blob(4096))
open(f"{root}/dir/hundred_blocks.bin", "wb").write(blob(100 * 4096 + 123))
# A file large enough to run past the inode's own pointers and both direct nodes
# into a single-indirect node: that boundary is near 11.5 MiB, so 13 MiB crosses
# it. Each 4 KiB block starts with its own index, the rest zeros, so the file
# compresses to almost nothing in the committed image yet every block is
# distinct: a reader that maps a block wrong hands back a different index and
# fails the hash. (blocks reached: inode 0..~866, direct node 1 and 2, then the
# first single-indirect node.)
BS = 4096
nblocks = (13 * 1024 * 1024) // BS
with open(f"{root}/dir/indirect.bin", "wb") as f:
    for i in range(nblocks):
        f.write(struct.pack("<Q", i) + b"F2FS-block" + bytes(BS - 18))
    f.write(struct.pack("<Q", nblocks) + b"tail\n")     # a short final block
open(f"{root}/dir/sub/deep.txt", "wb").write(b"deep file\n")
for i in range(600):
    open(f"{root}/manyfiles/f{i:04d}.txt", "wb").write(b"m%04d\n" % i)
os.symlink("dir/indirect.bin", f"{root}/link_to_indirect")
PY

# Full source-tree hash list, then split by whether the file fits in the inode.
( cd "$work/src" && find . -type f -print0 | sort -z | xargs -0 sha256sum | sed 's|  \./|  |' ) > "$work/all.sha256"
: > "$out/f2fs-fixture.src.sha256"
: > "$out/f2fs-fixture.nodes.sha256"
big_paths=()
while IFS= read -r line; do
    path=${line#*  }
    sz=$(stat -c%s "$work/src/$path")
    if [ "$sz" -le "$INLINE_MAX" ]; then
        printf '%s\n' "$line" >> "$out/f2fs-fixture.src.sha256"
    else
        big_paths+=("$path")
    fi
done < "$work/all.sha256"

truncate -s 256M "$work/f2fs.img"
run mkfs.f2fs -f -q \
    -O extra_attr,inode_checksum,flexible_inline_xattr,inode_crtime,sb_checksum,lost_found \
    "$work/f2fs.img" </dev/null
# sload.f2fs returns non-zero on a benign ownership note even when the write
# succeeded (it does not preserve owner without root), so its exit code is not a
# verdict. fsck.f2fs, run once, normalises the SIT type bits sload leaves and
# reports the valid-block counts; the real "is this image readable" gate is the
# independent dump.f2fs extraction below, which fails the build if it cannot read
# a file back. fsck rewrites in place, but only the SIT metadata, not file
# content, so the recorded hashes are unaffected.
run sload.f2fs -f "$work/src" -t / -T 1700000000 "$work/f2fs.img" </dev/null || true
run fsck.f2fs "$work/f2fs.img" </dev/null > "$work/fsck.log" 2>&1 || true
grep -iE "valid_(block|node|inode)" "$work/fsck.log" || true

# For each node-crossing file, find its inode by the i_name dump.f2fs prints, extract
# it with dump.f2fs (the independent reader) and record that hash.
for path in "${big_paths[@]}"; do
    base=$(basename "$path")
    ino=""                                       # dump.f2fs -i reads the inode number as hex
    for i in $(seq 3 400); do
        hexi=$(printf '%x' "$i")
        # dump.f2fs prints the file's own name in the i_name field; anchor on it
        # so the i_namelen line just above is not matched instead.
        # || true: a non-file inode has no i_name line, so grep exits non-zero
        # and pipefail would abort the script mid-scan.
        name=$(printf 'N\n' | run dump.f2fs -i "$hexi" "$work/f2fs.img" 2>/dev/null \
               | grep -aE '^i_name[[:space:]]' | sed -n 's/.*\[\(.*\)\]$/\1/p' | head -1) || true
        if [ "$name" = "$base" ]; then ino=$hexi; break; fi
    done
    [ -n "$ino" ] || { echo "could not find inode for $path" >&2; exit 1; }
    ex=$(mktemp -d)
    ( cd "$ex" && printf 'Y\n' | run dump.f2fs -i "$ino" "$work/f2fs.img" >/dev/null 2>&1 )
    got=$(find "$ex" -type f -name "$base" -exec sha256sum {} \; | head -1 | cut -d' ' -f1)
    rm -rf "$ex"
    [ -n "$got" ] || { echo "dump.f2fs did not extract $path" >&2; exit 1; }
    printf '%s  %s\n' "$got" "$path" >> "$out/f2fs-fixture.nodes.sha256"
done

gzip -9 -c "$work/f2fs.img" > "$out/f2fs-fixture.img.gz"
echo "wrote:"
ls -la "$out/f2fs-fixture.img.gz" "$out/f2fs-fixture.src.sha256" "$out/f2fs-fixture.nodes.sha256"
echo "src files:   $(wc -l < "$out/f2fs-fixture.src.sha256")"
echo "node files:  $(wc -l < "$out/f2fs-fixture.nodes.sha256")"
