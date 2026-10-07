#!/usr/bin/env bash
# Build tests/fixtures/yaffs2-history.img.gz and yaffs1-history.img.gz and the
# lists the self-test checks them against, with YAFFS's own code writing and
# reading them.
#
# Runs on Linux with a C compiler and no root. tools/yaffs_history.c is built
# against Aleph One's yaffs2 tree ($YAFFS2, default ~/flashfs-kit/yaffs2, commit
# 474b3acb927d27b2305618aaf24456b9d33fe91b): the real YAFFS core, driven through
# its "direct" interface, over a file that stands in for NAND (data then spare
# per page, writes that can only clear bits). YAFFS2 gets 2048-byte pages with
# a 64-byte spare, 32 blocks of 64 pages (4 MiB); YAFFS1 gets 512-byte pages
# with a 16-byte spare, 128 blocks of 32 pages (2 MiB).
#
# The history: overwrites in the middle of a file and past its end, a shrink
# then a truncate asking to grow, a shrink then data written past where the old
# data ended (the gap must read as zeros), a file written only far from its
# start, a deleted file, a rename, a symlink, a hard link whose first name is
# removed, more data written and deleted than the device holds (so garbage
# collection runs), and last a file whose data is flushed with fdatasync but
# never closed, so its header still gives its old size. Then the program exits
# without unmounting, so no checkpoint is written, as on a device imaged while
# it ran. The YAFFS1 image ends with a power cut: writing continues until
# garbage collection copies a live data chunk (the copy gets serial + 1), and
# the flash stops before the original is marked deleted, so two live copies
# remain and only their serial numbers tell the newer.
#
# A third image, yaffs1cut, isolates that rule where it changes the bytes: on a
# device of 67,584 chunks with wide tnodes off, YAFFS reads the old tags when it
# rewrites a chunk and gives the new copy serial + 1, so one chunk of one file is
# rewritten and the flash stops before the old copy is marked deleted.
#
# The oracle is YAFFS reading the image back: a copy is mounted read-only with
# the checkpoint skipped, so the flash itself is scanned, and every file it
# returns is hashed (yaffsN.history.sha256) and every entry's mode, size and
# mtime listed (yaffsN.history.stat).
set -euo pipefail

out=${1:-$(cd "$(dirname "$0")/.." && pwd)/tests/fixtures}
YAFFS2=${YAFFS2:-$HOME/flashfs-kit/yaffs2}
here=$(cd "$(dirname "$0")" && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

core=(allocator bitmap cache checkptrw ecc endian guts nameval nand packedtags1
      packedtags2 summary tagscompat tagsmarshall verify yaffs1 yaffs2)
srcs=("$here/yaffs_history.c"
      "$YAFFS2/direct/yaffsfs.c" "$YAFFS2/direct/yaffs_hweight.c"
      "$YAFFS2/direct/yaffs_error.c" "$YAFFS2/direct/yaffs_attribs.c"
      "$YAFFS2/direct/optional_sort/qsort.c"
      "$YAFFS2/direct/test-framework/yaffs_osglue.c")
for c in "${core[@]}"; do srcs+=("$YAFFS2/core/yaffs_$c.c"); done
gcc -O1 -w -DCONFIG_YAFFS_DIRECT -DCONFIG_YAFFS_YAFFS2 -DCONFIG_YAFFS_DEFINES_TYPES \
    -DCONFIG_YAFFS_PROVIDE_DEFS -DCONFIG_YAFFSFS_PROVIDE_VALUES \
    -I"$YAFFS2/core" -I"$YAFFS2/direct" -I"$YAFFS2/direct/test-framework" \
    -o "$work/yaffs_history" "${srcs[@]}" -lpthread

for v in yaffs2 yaffs1 yaffs1cut; do
    "$work/yaffs_history" "$v" write "$work/$v.img"
    cp "$work/$v.img" "$work/$v.ro"
    "$work/yaffs_history" "$v" dump "$work/$v.ro" "$work/$v.dump"
    cmp -s "$work/$v.img" "$work/$v.ro" || { echo "the read-only mount changed $v" >&2; exit 1; }
    ( cd "$work/$v.dump/files" && find . -type f -print0 | sort -z | xargs -0 sha256sum \
        | sed 's|  \./|  |' ) > "$out/$v.history.sha256"
    sort -k4 "$work/$v.dump/listing" > "$out/$v.history.stat"
    gzip -9 -n -c "$work/$v.img" > "$out/$v-history.img.gz"
    printf '%s-history %d bytes, %d gzipped; %d files, %d entries read back by YAFFS\n' "$v" \
        "$(stat -c%s "$work/$v.img")" "$(stat -c%s "$out/$v-history.img.gz")" \
        "$(wc -l < "$out/$v.history.sha256")" "$(wc -l < "$out/$v.history.stat")"
done
