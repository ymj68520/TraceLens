#!/bin/bash
# Build the populated APFS image qnxprobe's self-test walks, and record what
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
#     bash tools/make_apfs_fixture.sh /tmp/apfs-fixture.img 48
set -euo pipefail

IMG=${1:-apfs-fixture.img}
MIB=${2:-48}
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
hdiutil create -size "${MIB}m" -fs "APFS" -volname QNXPROBE -type UDIF \
  -layout NONE -quiet "$WORK/img.dmg"
hdiutil attach "$WORK/img.dmg" -nobrowse -readwrite -mountpoint "$MNT" -quiet

printf 'a small file that fits in one block\n' > "$MNT/small.txt"
: > "$MNT/empty.bin"
fill "$MNT/medium.bin" 240000 'medium payload line'

mkdir -p "$MNT/dir/sub"
printf 'two levels down\n' > "$MNT/dir/sub/deep.txt"
printf 'one level down\n' > "$MNT/dir/mid.txt"
printf 'unicode name\n' > "$MNT/ünïcödé ñâmé.txt"

# enough entries that the file-system B-tree is more than one node deep
mkdir -p "$MNT/many"
for i in $(seq 1 400); do printf 'entry %s\n' "$i" > "$MNT/many/file_$(printf '%04d' "$i").txt"; done

ln -s small.txt "$MNT/link.txt"

# two names for one inode
printf 'one inode, two names\n' > "$MNT/hard_a.txt"
ln "$MNT/hard_a.txt" "$MNT/hard_b.txt"

# a sparse file: a hole, then data past it
python3 -c "
import sys
p = sys.argv[1]
with open(p, 'wb') as fh:
    fh.truncate(1 << 20)
    fh.seek(1 << 20)
    fh.write(b'tail after a hole\n')" "$MNT/sparse.bin"

# a compressed file. The attribute is written directly and the flag set: this
# machine's driver reports the size and hands back nothing when it is read,
# while The Sleuth Kit decompresses it, so the plaintext is written out here and
# used as the expected answer rather than a read of the mounted volume.
python3 - "$MNT/decmpfs.txt" "$OUT/decmpfs.expected" <<'DECMPFS'
import hashlib, struct, subprocess, sys, zlib
raw = ("a compressible line of text\n" * 4000).encode()
blob = b"fpmc" + struct.pack("<I", 3) + struct.pack("<Q", len(raw)) + zlib.compress(raw, 9)
open(sys.argv[1], "wb").write(b"")
subprocess.run(["xattr", "-w", "-x", "com.apple.decmpfs", blob.hex(), sys.argv[1]], check=True)
subprocess.run(["chflags", "compressed", sys.argv[1]], check=True)
open(sys.argv[2], "w").write(hashlib.sha256(raw).hexdigest())
DECMPFS

# a file in many pieces: fill the volume, delete every other file, write the
# survivor into the holes, then remove the fillers, so the fixture keeps the
# fragmented extent list without keeping the files that produced it
mkdir -p "$MNT/holes"
i=0
while [ $i -lt 6000 ]; do
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
# A symbolic link is left out of this comparison: The Sleuth Kit will not
# produce an APFS link's target, so there is no independent reading to compare
# against. The walker's own reading of it is checked by the self-test instead.
(cd "$MNT" && find . -type f ! -name '.DS_Store' -print0 | sort -z \
  | xargs -0 shasum -a 256 | sort -k2) > "$OUT/intended.tmp"
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

python3 - "$IMG" "$OUT/oracle.sha256" <<'ORACLE'
import hashlib, re, subprocess, sys
img, out = sys.argv[1], sys.argv[2]
# The volume's superblock block number is what The Sleuth Kit addresses a volume
# inside a container by, and its own pool listing is where that number comes from.
pool = subprocess.run(["pstat", img], capture_output=True, text=True).stdout
m = re.search(r"APSB Block Number:\s*(\d+)", pool)
if not m:
    print("could not find the volume's superblock block in the pool listing", file=sys.stderr)
    raise SystemExit(1)
block = m.group(1)
listing = subprocess.run(["fls", "-f", "apfs", "-B", block, "-r", "-p", img],
                         capture_output=True, text=True).stdout
rows = []
for line in listing.splitlines():
    if "\t" not in line:
        continue
    meta, path = line.split("\t", 1)
    parts = meta.split()
    if parts[0] != "r/r" or "*" in parts:
        continue
    ino = parts[-1].rstrip(":")
    data = subprocess.run(["icat", "-f", "apfs", "-B", block, img, ino],
                          capture_output=True).stdout
    rows.append(f"{hashlib.sha256(data).hexdigest()}  ./{path}")
rows.sort(key=lambda r: r.split("  ", 1)[1])
open(out, "w").write("\n".join(rows) + "\n")
print(f"  the oracle read {len(rows)} files", file=sys.stderr)
ORACLE

if diff -q "$OUT/intended.sha256" "$OUT/oracle.sha256" >/dev/null; then
  echo "oracle agrees with what was written: $(wc -l < "$OUT/oracle.sha256" | tr -d ' ') files"
else
  echo "ORACLE DISAGREES WITH INTENT"; diff "$OUT/intended.sha256" "$OUT/oracle.sha256" | head -20; exit 1
fi
ls -l "$IMG"
