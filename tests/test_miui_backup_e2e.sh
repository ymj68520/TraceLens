#!/usr/bin/env bash
set -euo pipefail

BACKUP="${1:-/home/ymj68520/projects/Forensics/AndroidBackup}"
OUT="$(mktemp -d)"
cleanup() {
    rm -rf "$OUT"
}
trap cleanup EXIT

./build/forensic_analyzer "$BACKUP" --android-analyze --android-source miui-backup --db-dir "$OUT"
DB="$OUT/$(basename "$BACKUP")_files.db"
test -f "$DB"

# Manifest + inventory populated.
sqlite3 "$DB" "SELECT count(*) FROM miui_backup_manifest;" | grep -qv '^0$'
sqlite3 "$DB" "SELECT count(*) FROM app_db_inventory;" | grep -qv '^0$'

# A known real DB surfaces via the generic analyzer OR the inventory.
sqlite3 "$DB" "SELECT package_name FROM app_db_inventory WHERE package_name='com.android.email' LIMIT 1;" \
    | grep -q 'com.android.email'

echo "MIUI backup E2E OK"
