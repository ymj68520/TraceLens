#!/bin/bash
# Build the populated HFS+ image qnxprobe's self-test walks, and record what
# went into it.
#
# Runs on macOS, as an ordinary user: hdiutil creates and mounts a plain image
# file, so no root and no third-party tool. The filesystem is written by the
# operating system's own driver, so neither the image nor the expected answers
# come from the reader they are used to test.
#
# Three statements of the same truth have to agree: what this script meant to
# write, what an independent reader finds in the finished image, and what
# qnxprobe finds. The first two are compared here and the run fails if they
# disagree; the third is the self-test.
#
#     bash tools/make_hfsplus_fixture.sh /tmp/hfsplus-fixture.img 24
set -euo pipefail

IMG=${1:-hfsplus-fixture.img}
MIB=${2:-24}
OUT=$(dirname "$IMG")
WORK=$(mktemp -d)
MNT="$WORK/mnt"
mkdir -p "$MNT"

cleanup() { hdiutil detach "$MNT" -quiet 2>/dev/null || true; rm -rf "$WORK"; }
trap cleanup EXIT

fill() {  # fill <path> <bytes> <line> [append]
  python3 -c 'import sys
path, size, line, mode = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
block = ((line + "\n") * (size // (len(line) + 1) + 1))[:size].encode()
open(path, "ab" if mode == "append" else "wb").write(block)' "$1" "$2" "$3" "${4:-}"
}

rm -f "$IMG" "$WORK/img.dmg"
# -layout NONE writes the filesystem with no partition map, so the image is the
# volume: that is what a walker is handed when a partition is carved out of a
# larger image, and it keeps the fixture free of a second format to parse.
hdiutil create -size "${MIB}m" -fs "HFS+" -volname QNXPROBE -type UDIF \
  -layout NONE -quiet "$WORK/img.dmg"
hdiutil attach "$WORK/img.dmg" -nobrowse -readwrite -mountpoint "$MNT" -quiet

# 1. an ordinary small file, and an empty one
printf 'a small file that fits in one allocation block\n' > "$MNT/small.txt"
: > "$MNT/empty.bin"

# 2. a file of several allocation blocks in one extent
fill "$MNT/medium.bin" 240000 'medium payload line'

# 3. nesting
mkdir -p "$MNT/dir/sub"
printf 'two levels down\n' > "$MNT/dir/sub/deep.txt"
printf 'one level down\n' > "$MNT/dir/mid.txt"

# 4. a name that needs UTF-16 to survive. HFS+ stores names decomposed, so this
#    also exercises the reader handing back what the catalog holds.
printf 'unicode name\n' > "$MNT/ünïcödé ñâmé.txt"

# 5. enough entries that the catalog B-tree is more than one node deep
mkdir -p "$MNT/many"
for i in $(seq 1 400); do printf 'entry %s\n' "$i" > "$MNT/many/file_$(printf '%04d' "$i").txt"; done

# 6. a symbolic link, which HFS+ stores as a file whose data is the target
ln -s small.txt "$MNT/link.txt"

# 7. two names for one file. HFS+ does this with an indirect node in a private
#    directory at the volume root, so following it is its own code path.
printf 'one record, two names\n' > "$MNT/hard_a.txt"
ln "$MNT/hard_a.txt" "$MNT/hard_b.txt"

# 8. a resource fork, which is a second fork on the same catalog record
printf 'the data fork\n' > "$MNT/forked.txt"
printf 'the resource fork\n' > "$MNT/forked.txt/..namedfork/rsrc"

# 9. a compressed file. macOS will not compress one on demand here, so the
#    decmpfs attribute is written directly and the flag set: the structure is
#    the documented one and an independent reader decompresses it, which is what
#    the comparison below checks.
#     This machine's own driver reports the size of a file compressed this way
#     but hands back nothing when it is read, while The Sleuth Kit decompresses
#     it, so the plaintext is written out here and used as the expected answer
#     rather than a read of the mounted volume.
python3 - "$MNT/decmpfs.txt" "$OUT/decmpfs.expected" <<'DECMPFS'
import hashlib, struct, subprocess, sys, zlib
raw = ("a compressible line of text\n" * 4000).encode()
blob = b"fpmc" + struct.pack("<I", 3) + struct.pack("<Q", len(raw)) + zlib.compress(raw, 9)
open(sys.argv[1], "wb").write(b"")
subprocess.run(["xattr", "-w", "-x", "com.apple.decmpfs", blob.hex(), sys.argv[1]], check=True)
subprocess.run(["chflags", "compressed", sys.argv[1]], check=True)
open(sys.argv[2], "w").write(hashlib.sha256(raw).hexdigest())
DECMPFS

# 10. a file fragmented past the eight extent descriptors a catalog record holds,
#     so the rest of its extents live in the extents overflow B-tree. The volume
#     is filled, every other file deleted, the survivor written into the holes,
#     and the fillers then removed, so the fixture keeps the fragmented file
#     without keeping the thousands of files that produced it.
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
echo "  filled with $i small files, then emptied, to fragment one survivor" >&2

sync
# What the generator meant to write. The compressed file is listed by its
# plaintext, which is what any reader has to hand back.
# A symbolic link is included: HFS+ stores its target as the file's data, so a
# reader has to hand that back, and both sides of this comparison can say what
# it should be.
(cd "$MNT" && { find . -type f ! -name '.DS_Store' -print0 | sort -z | xargs -0 shasum -a 256
  find . -type l -print0 | sort -z | while IFS= read -r -d "" l; do
    printf '%s  %s\n' "$(readlink "$l" | tr -d '\n' | shasum -a 256 | cut -d' ' -f1)" "$l"
  done; } | sort -k2) > "$OUT/intended.tmp"
python3 - "$OUT/intended.tmp" "$OUT/decmpfs.expected" "$OUT/intended.sha256" <<'SPLICE'
import sys
rows = open(sys.argv[1]).read().splitlines()
want = open(sys.argv[2]).read().strip()
out = [f"{want}  ./decmpfs.txt" if r.endswith("./decmpfs.txt") else r for r in rows]
open(sys.argv[3], "w").write("\n".join(out) + "\n")
SPLICE
rm -f "$OUT/intended.tmp" "$OUT/decmpfs.expected"
hdiutil detach "$MNT" -quiet

cp "$WORK/img.dmg" "$IMG"

# The oracle: read the finished image with The Sleuth Kit, which is a different
# implementation of the same format and never saw the generator.
python3 - "$IMG" "$OUT/oracle.sha256" <<'PY'
import hashlib, subprocess, sys
img, out = sys.argv[1], sys.argv[2]
listing = subprocess.run(["fls", "-f", "hfs", "-r", "-p", img],
                         capture_output=True, text=True).stdout
rows = []
for line in listing.splitlines():
    if "\t" not in line:
        continue
    meta, path = line.split("\t", 1)
    parts = meta.split()
    if parts[0] not in ("r/r", "l/l") or "*" in parts:
        continue
    # The private directories hold the indirect nodes a hard link points at
    # and the volume's own B-trees. They are real, and they are not what the
    # generator wrote, so they are not part of this comparison.
    if path.startswith("$") or "HFS+ Private" in path:
        continue
    ino = parts[-1].rstrip(":")
    data = subprocess.run(["icat", "-f", "hfs", img, ino],
                          capture_output=True).stdout
    rows.append(f"{hashlib.sha256(data).hexdigest()}  ./{path}")
rows.sort(key=lambda r: r.split("  ", 1)[1])
open(out, "w").write("\n".join(rows) + "\n")
print(f"  the oracle read {len(rows)} files", file=sys.stderr)
PY

if diff -q "$OUT/intended.sha256" "$OUT/oracle.sha256" >/dev/null; then
  echo "oracle agrees with what was written: $(wc -l < "$OUT/oracle.sha256" | tr -d ' ') files"
else
  echo "ORACLE DISAGREES WITH INTENT"
  diff "$OUT/intended.sha256" "$OUT/oracle.sha256" | head -20
  exit 1
fi
ls -l "$IMG"
