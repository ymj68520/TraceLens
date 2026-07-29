#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_UNDER_TEST="$SCRIPT_DIR/test_miui_backup_e2e.sh"
TEST_ROOT="$(mktemp -d /tmp/tracelens-miui-e2e-safety.XXXXXX)"
cleanup() {
    rm -rf "$TEST_ROOT"
}
trap cleanup EXIT

EVIDENCE="$TEST_ROOT/evidence"
WORKSPACE="$TEST_ROOT/workspace"
ANALYZER_LOG="$TEST_ROOT/analyzer-db-dir"
mkdir -p "$EVIDENCE/tmpdir" "$WORKSPACE/build" "$WORKSPACE/tests"
ln -s "$SCRIPT_UNDER_TEST" "$WORKSPACE/tests/test_miui_backup_e2e.sh"

cat > "$WORKSPACE/build/forensic_analyzer" <<'ANALYZER'
#!/usr/bin/env bash
set -euo pipefail

output=""
while (($#)); do
    case "$1" in
        --db-dir)
            output="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

printf '%s\n' "$output" > "$FAKE_ANALYZER_LOG"
database="$output/$(basename "$FAKE_BACKUP")_files.db"
sqlite3 "$database" "
    CREATE TABLE miui_backup_manifest (device TEXT);
    CREATE TABLE app_db_inventory (package_name TEXT);
    INSERT INTO miui_backup_manifest VALUES ('test-device');
    INSERT INTO app_db_inventory VALUES ('com.android.email');
"
ANALYZER
chmod +x "$WORKSPACE/build/forensic_analyzer"

(
    cd "$WORKSPACE"
    TMPDIR="$EVIDENCE/tmpdir" \
        FAKE_ANALYZER_LOG="$ANALYZER_LOG" \
        FAKE_BACKUP="$EVIDENCE" \
        bash tests/test_miui_backup_e2e.sh "$EVIDENCE"
)

output_dir="$(<"$ANALYZER_LOG")"
case "$output_dir" in
    "$EVIDENCE"|"$EVIDENCE"/*)
        printf 'FAIL: smoke output was placed under evidence: %s\n' "$output_dir" >&2
        exit 1
        ;;
esac

test ! -e "$output_dir"
echo "MIUI backup TMPDIR safety OK"
