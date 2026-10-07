#!/bin/bash
# Build the populated NTFS image qnxprobe's self-test walks, and record what
# went into it.
#
# Runs on Linux, as an ordinary user: ntfs-3g mounts a plain image file through
# FUSE, so no loop device and no root are needed. mkntfs writes the filesystem
# and ntfs-3g writes the content, so neither the image nor the expected answers
# come from the reader they are used to test.
#
# Three statements of the same truth have to agree: what this script meant to
# write, what an independent reader finds in the finished image, and what
# qnxprobe finds. The first two are compared here and the run fails if they
# disagree; the third is the self-test.
#
# The image is committed gzipped as tests/fixtures/ntfs-fixture.img.gz and the
# hashes as tests/fixtures/ntfs-fixture.sha256, with the leading "./" stripped.
#
#     bash tools/make_ntfs_fixture.sh /tmp/ntfs-fixture.img 16
set -euo pipefail

# `yes | head -c` would do, but head's exit kills yes with SIGPIPE, which under
# `set -o pipefail` aborts the script silently. Write the bytes directly instead.
fill() {  # fill <path> <bytes> <line> [append]
  python3 -c 'import sys
path, size, line, mode = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
block = ((line + "\n") * (size // (len(line) + 1) + 1))[:size].encode()
open(path, "ab" if mode == "append" else "wb").write(block)' "$1" "$2" "$3" "${4:-}"
}

IMG=${1:-ntfs-fixture.img}
MIB=${2:-16}
MNT=$(mktemp -d)
OUT=$(dirname "$IMG")

cleanup() { mountpoint -q "$MNT" && fusermount3 -u "$MNT" 2>/dev/null || true; rmdir "$MNT" 2>/dev/null || true; }
trap cleanup EXIT

rm -f "$IMG"
dd if=/dev/zero of="$IMG" bs=1M count="$MIB" status=none
mkntfs -F -f -Q -L QNXPROBE -s 512 -c 4096 "$IMG" >/dev/null
ntfs-3g "$IMG" "$MNT"

# 1. resident data: small enough to live inside the MFT record
printf 'resident stream, small enough to sit inside the MFT record\n' > "$MNT/small.txt"

# 2. an empty file: a zero-length data attribute
: > "$MNT/empty.bin"

# 3. non-resident data in one run. The content repeats rather than being random,
#    so the committed image packs to a fraction of its size; what the walker has
#    to get right is the extent, not the entropy.
fill "$MNT/medium.bin" 200000 'medium.bin payload line'

# 4. a name that needs UTF-16 to survive, with spaces
printf 'unicode name\n' > "$MNT/ünïcödé ñâmé.txt"

# 5. nesting, with a small directory index that fits in INDEX_ROOT
mkdir -p "$MNT/dir/sub"
printf 'two levels down\n' > "$MNT/dir/sub/deep.txt"
printf 'one level down\n' > "$MNT/dir/mid.txt"

# 6. a directory big enough to need INDEX_ALLOCATION, so INDX blocks and their
#    fixups are exercised rather than just the resident index root
mkdir -p "$MNT/many"
for i in $(seq 1 400); do printf 'entry %s\n' "$i" > "$MNT/many/file_$(printf '%04d' "$i").txt"; done

# 7. fragmentation: interleave two growing files, then delete the filler, so the
#    survivor's data runs are not contiguous
mkdir -p "$MNT/frag"
for i in $(seq 1 24); do
  fill "$MNT/frag/target.bin" 65536 "target.bin block $i" append
  fill "$MNT/frag/filler_$i.bin" 65536 "filler $i"
done
rm -f "$MNT"/frag/filler_*.bin

# 8. a sparse file: a hole followed by data
python3 - "$MNT/sparse.bin" <<'PY'
import sys
with open(sys.argv[1], "wb") as fh:
    fh.truncate(1 << 20)
    fh.seek(1 << 20)
    fh.write(b"tail after a hole\n")
PY

# 9. an alternate data stream, written on a second mount: the Windows stream
#    interface makes "file:stream" a path, and it is kept off the manifest
#    because a stream is not a file the walker should report as one
printf 'the visible stream\n' > "$MNT/ads.txt"

# 10. a compressed file. The directory carries FILE_ATTRIBUTE_COMPRESSED and the
#     driver compresses what is written into it, which is the only way to reach
#     the LZNT1 path without a Windows machine.
mkdir -p "$MNT/comp"
python3 -c 'import os, struct, sys; os.setxattr(sys.argv[1], "system.ntfs_attrib", struct.pack("<I", 0x810))' "$MNT/comp"
fill "$MNT/comp/text.bin" 660000 'a line that repeats and so compresses well'

# 11. a record whose attributes do not fit in it. Every extra name is another
#     $FILE_NAME attribute, so enough hard links overflow the record and push
#     the rest into other records, leaving an $ATTRIBUTE_LIST that says where
#     they went. That is the same overflow a heavily fragmented file causes and
#     it costs one cluster instead of filling the volume.
mkdir -p "$MNT/links"
printf 'one record, many names\n' > "$MNT/links/base.txt"
for i in $(seq 1 60); do ln "$MNT/links/base.txt" "$MNT/links/name_$(printf '%02d' "$i").txt"; done

# 12. a file fragmented far enough that its run list cannot fit in its own MFT
#     record either, so the $DATA itself moves out. The volume is filled, every
#     other file deleted, the survivor written into the holes, and the fillers
#     then removed: the fixture keeps the fragmented run list without keeping
#     the thousands of files that produced it.
mkdir -p "$MNT/holes"
i=0
while [ $i -lt 4000 ]; do
  i=$((i + 1))
  fill "$MNT/holes/h_$i.bin" 4096 "hole $i" 2>/dev/null || { rm -f "$MNT/holes/h_$i.bin"; i=$((i - 1)); break; }
done
j=1
while [ $j -le $i ]; do rm -f "$MNT/holes/h_$j.bin"; j=$((j + 2)); done
fill "$MNT/holes/spread.bin" $(( (i / 2) * 4096 )) 'spread across whatever holes are left' 2>/dev/null \
  || fill "$MNT/holes/spread.bin" $(( (i / 4) * 4096 )) 'spread across whatever holes are left'
rm -f "$MNT"/holes/h_*.bin
echo "  filled with $i files, then emptied, to fragment one survivor" >&2

# 13. a file grown past what was written into it. Everything between the
#     initialized size and the end reads as zero even though the clusters are
#     allocated and still hold whatever was there before, which is the shape a
#     database that preallocates its file has.
fill "$MNT/grown.bin" 65536 'written part of a file that was then grown'
truncate -s 1048576 "$MNT/grown.bin"

# 14. two names for one file
printf 'one record, two names\n' > "$MNT/linked_a.txt"
ln "$MNT/linked_a.txt" "$MNT/linked_b.txt"

sync
fusermount3 -u "$MNT"
ntfs-3g -o streams_interface=windows "$IMG" "$MNT"
printf 'the hidden stream\n' > "$MNT/ads.txt:hidden" \
  && echo "  wrote an alternate data stream" >&2 \
  || echo "  NOTE: could not write an alternate data stream" >&2
sync
fusermount3 -u "$MNT"
ntfs-3g "$IMG" "$MNT"

# 15. deleted files, created last and then removed so nothing reuses their
#     records or clusters. A small one stays resident (its bytes live inside the
#     MFT record, which is the only deleted content a carver can never reach),
#     and a larger one is non-resident in free clusters. Their content is hashed
#     before deletion, so the expected answer comes from what was written rather
#     than from any reader. Recorded to deleted.intended as "<sha256> <name>".
mkdir -p "$MNT/deleted"
printf 'resident deleted file: these bytes live inside the MFT record itself, so no carver can reach them. %s\n' \
  "$(head -c 200 /dev/zero | tr '\0' 'r')" > "$MNT/deleted/resident-note.txt"
fill "$MNT/deleted/recording.bin" 300000 'non-resident deleted payload line, recoverable while its clusters stay free'
sync
: > "$OUT/deleted.intended"
for f in resident-note.txt recording.bin; do
  printf '%s  %s\n' "$(sha256sum "$MNT/deleted/$f" | cut -d" " -f1)" "$f" >> "$OUT/deleted.intended"
done
rm -f "$MNT/deleted/resident-note.txt" "$MNT/deleted/recording.bin"
rmdir "$MNT/deleted" 2>/dev/null || true
sync
echo "  wrote and deleted $(wc -l < "$OUT/deleted.intended") files for recovery testing" >&2

find "$MNT" -type f -printf '%P\t%s\n' | sort > "$OUT/paths.tsv"
(cd "$MNT" && find . -type f -print0 | sort -z | xargs -0 sha256sum) > "$OUT/intended.sha256"
find "$MNT" -type d -printf '%P\n' | sort > "$OUT/dirs.txt"

fusermount3 -u "$MNT"

# The oracle: read the finished image back with an independent implementation
ntfs-3g -o ro "$IMG" "$MNT"
(cd "$MNT" && find . -type f -print0 | sort -z | xargs -0 sha256sum) > "$OUT/oracle.sha256"
find "$MNT" -printf '%y\t%P\t%s\t%T@\n' | sort > "$OUT/oracle.listing"
fusermount3 -u "$MNT"

if diff -q "$OUT/intended.sha256" "$OUT/oracle.sha256" >/dev/null; then
  echo "oracle agrees with what was written: $(wc -l < "$OUT/oracle.sha256") files"
else
  echo "ORACLE DISAGREES WITH INTENT"; diff "$OUT/intended.sha256" "$OUT/oracle.sha256" | head; exit 1
fi
ls -l "$IMG"
