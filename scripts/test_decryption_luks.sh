#!/usr/bin/env bash
# scripts/test_decryption_luks.sh
#
# End-to-end test of the ImageAnalyzer decryption module using a controlled
# LUKS-encrypted image with a KNOWN password. Verifies the whole flow:
#   1. Create a LUKS2 image with a known password + ext4 filesystem + marker files
#   2. Write the password to a sibling .key file (KeyFileLoader convention)
#   3. Run forensic_analyzer --decrypt and confirm the encrypted volume is
#      detected, decrypted, and the marker files appear in _raw.db
#
# Requires: cryptsetup, losetup, mkfs.ext4, sudo (for losetup/cryptsetup).
# Must be run as root (the tool itself calls losetup/cryptsetup).
set -euo pipefail

ANALYZER="${ANALYZER:-$(dirname "$0")/../build/forensic_analyzer}"
WORK="$(mktemp -d /tmp/dec_test.XXXXXX)"
IMG="$WORK/secret_disk.img"
KEY="$WORK/secret_disk.key"
OUT="$WORK/out"
PASS="TestLUKSpass!2026"

echo "=== Decryption end-to-end test (LUKS) ==="
echo "work dir: $WORK"

# --- Step 1: create LUKS2 image with known password ---
echo "[1/4] Creating LUKS2 image ($PASS)..."
truncate -s 256M "$IMG"
# Format (non-interactive, password via key-file with NO trailing newline).
# Both format and open must use the identical key bytes, so write the password
# to a temp file and pass it with --key-file for both operations.
KEYTMP="$WORK/.luks_key"
printf '%s' "$PASS" > "$KEYTMP"; chmod 600 "$KEYTMP"
cryptsetup luksFormat --type luks2 --batch-mode --key-file="$KEYTMP" "$IMG"
# Open, make ext4, drop marker files, close
LOOP="$(losetup -f --show "$IMG")"
cryptsetup open --key-file="$KEYTMP" "$LOOP" test_luks_vol
mkfs.ext4 -q /dev/mapper/test_luks_vol
MNT="$(mktemp -d)"
mount /dev/mapper/test_luks_vol "$MNT"
echo "TOP-SECRET-MARKER-12345" > "$MNT/confidential.txt"
mkdir -p "$MNT/case_evidence"
echo "suspect log line" > "$MNT/case_evidence/log.txt"
umount "$MNT"
rmdir "$MNT"
cryptsetup close test_luks_vol
losetup -d "$LOOP"
rm -f "$KEYTMP"

# --- Step 2: write sibling .key file (whole-image convention: <base>.key) ---
echo "[2/4] Writing sibling .key file..."
printf '%s' "$PASS" > "$KEY"
chmod 600 "$KEY"
echo "  -> $KEY"

# --- Step 3: run forensic_analyzer with --decrypt ---
echo "[3/4] Running forensic_analyzer --decrypt ..."
set +e
"$ANALYZER" "$IMG" --decrypt --db-dir "$OUT" 2>&1 | tee "$WORK/run.log"
RC=${PIPESTATUS[0]}
set -e

if [ "$RC" -ne 0 ]; then
  echo "FAIL: analyzer exited non-zero (rc=$RC)"; exit 1
fi

# --- Step 4: verify marker files were extracted ---
echo "[4/4] Verifying extracted files in _raw.db..."
RAWDB="$OUT/secret_disk_raw.db"
if [ ! -f "$RAWDB" ]; then echo "FAIL: $RAWDB not found"; exit 1; fi

COUNT=$(sqlite3 "$RAWDB" "SELECT COUNT(*) FROM files;" 2>/dev/null || echo 0)
echo "  files extracted: $COUNT"
if [ "$COUNT" -lt 1 ]; then echo "FAIL: no files extracted from encrypted volume"; exit 1; fi

HAS_MARKER=$(sqlite3 "$RAWDB" "SELECT COUNT(*) FROM files WHERE name='confidential.txt' OR path LIKE '%confidential.txt';" 2>/dev/null || echo 0)
echo "  confidential.txt present: $HAS_MARKER"
if [ "$HAS_MARKER" -lt 1 ]; then echo "FAIL: marker file not extracted (decryption did not work)"; exit 1; fi

echo ""
echo "SUCCESS: LUKS volume decrypted and extracted ($COUNT files, marker found)."
echo "=== Test PASSED ==="
