#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TESTS_DIR="$ROOT_DIR/tests"
IMAGE_ORIG="$TESTS_DIR/android_test.img"
IMAGE_GEN="$TESTS_DIR/android_test_gen.img"
RESULTS="$TESTS_DIR/AndroidTestResults.md"

echo "Running Android Analyzer tests" > "$RESULTS"
echo "Generated on: $(date --iso-8601=seconds)" >> "$RESULTS"
echo "" >> "$RESULTS"

echo "[TEST] Baseline run: existing image ($IMAGE_ORIG)" >> "$RESULTS"
echo "----------------------------------------------------------------" >> "$RESULTS"
cd "$ROOT_DIR"
if [ -x build/forensic_analyzer ]; then
    build/forensic_analyzer "$IMAGE_ORIG" --android-analyze |& tee -a "$RESULTS"
else
    echo "Error: build/forensic_analyzer not found or not executable. Build the project first." | tee -a "$RESULTS"
    exit 1
fi

echo "" >> "$RESULTS"
echo "[TEST] Generate new Android test image with sample DBs ($IMAGE_GEN)" >> "$RESULTS"
echo "----------------------------------------------------------------" >> "$RESULTS"
tests/create_android_image.sh >> "$RESULTS" 2>&1 || { echo "Image creation failed" | tee -a "$RESULTS"; exit 1; }

echo "" >> "$RESULTS"
echo "[TEST] Run analyzer on generated image ($IMAGE_GEN)" >> "$RESULTS"
echo "----------------------------------------------------------------" >> "$RESULTS"
build/forensic_analyzer "$IMAGE_GEN" --android-analyze |& tee -a "$RESULTS"

echo "" >> "$RESULTS"
echo "Test run complete. Please inspect $RESULTS for details." >> "$RESULTS"

echo "Note: The generated image $IMAGE_GEN and the created database files are intentionally not cleaned up as requested." >> "$RESULTS"
