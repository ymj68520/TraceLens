#!/bin/bash
# Build the FAT32 and exFAT images the self-test recovers deleted files from.
# Each carries a folder of two photographs and one fragmented photograph, all
# created and then deleted; their content is hashed before deletion, so the
# expected answer comes from what was written. On a machine with The Sleuth Kit,
# `icat` on the same deleted entries confirms the same bytes independently.
#
# Runs on macOS (hdiutil) or Linux (mkfs.vfat / mkfs.exfat + a mount). This is
# the macOS form, which is how the committed fixtures were made.
#
#     bash tools/make_fat_deleted_fixtures.sh /tmp/out
set -euo pipefail
OUT=${1:-.}
py() { python3 -c "$1" "$2"; }

build() {  # build <fs> <fsargs> <label> <stem>
  local fs="$1" fsargs="$2" label="$3" stem="$4"
  local img="$OUT/$stem.img"
  rm -f "$img"
  if [ -n "$fsargs" ]; then
    hdiutil create -size 64m -fs "$fs" -fsargs "$fsargs" -volname "$label" -layout NONE "$img.dmg" -quiet
  else
    hdiutil create -size 64m -fs "$fs" -volname "$label" -layout NONE "$img.dmg" -quiet
  fi
  hdiutil attach "$img.dmg" -nobrowse -quiet; sleep 1
  local V="/Volumes/$label"
  mkdir "$V/photos"
  python3 -c 'import sys; from PIL import Image; Image.new("RGB",(300,200),(200,40,40)).save(sys.argv[1],"JPEG",quality=90)' "$V/photos/one.jpg"
  python3 -c 'import sys; from PIL import Image; Image.new("RGB",(300,200),(40,200,40)).save(sys.argv[1],"JPEG",quality=90)' "$V/photos/two.jpg"
  # write three fillers, delete the middle one, then a photo into the hole and beyond
  for n in a b c; do head -c 8192 /dev/zero | tr '\0' "$n" > "$V/$n.bin"; done; sync
  rm -f "$V/b.bin"; sync
  python3 -c 'import sys; from PIL import Image; Image.new("RGB",(640,480),(60,60,200)).save(sys.argv[1],"JPEG",quality=95)' "$V/frag-deleted.jpg"
  sync
  : > "$OUT/$stem.deleted.sha256"
  for f in photos/one.jpg photos/two.jpg frag-deleted.jpg; do
    printf '%s  %s\n' "$(shasum -a256 "$V/$f" | cut -d' ' -f1)" "$f" >> "$OUT/$stem.deleted.sha256"
  done
  rm -rf "$V/photos" "$V/frag-deleted.jpg"; sync; sleep 1
  hdiutil detach "$V" -quiet
  gzip -9 -c "$img.dmg" > "$OUT/$stem.img.gz"; rm -f "$img.dmg"
  echo "wrote $OUT/$stem.img.gz and $OUT/$stem.deleted.sha256"
}

build "MS-DOS" "-F 32" FATDELIVER fat32-deleted
build "ExFAT"  ""      EXFATDELIVER exfat-deleted
