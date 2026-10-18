#!/bin/bash
# RCA-2A.2d: one CLI scenario run + evidence collection
set -u
SCENARIO="$1"
ROOT="/home/ymj68520/projects/TraceLens/python_service"
H="$ROOT/benchmarks/audits/rca2a2d-cf1-settlement/harness"
RES="$H/results/$SCENARIO"
EV="$H/evidence"
rm -rf "$RES" "$EV/cf1d-$SCENARIO-model-calls.jsonl" "$EV/cf1d-$SCENARIO-diagnostics.jsonl"
mkdir -p "$RES"
cd "$ROOT"
RCA2A2C_PY_SERVICE_ROOT="$ROOT" \
RCA2A2D_SCENARIO="$SCENARIO" \
RCA2A2C_EVIDENCE_PATH="$EV/cf1d-$SCENARIO-model-calls.jsonl" \
LLM_FAILURE_DIAGNOSTICS=1 \
LLM_FAILURE_DIAGNOSTICS_PATH="$EV/cf1d-$SCENARIO-diagnostics.jsonl" \
PYTHONPATH="$H" \
.venv/bin/python scripts/run_p8b_baseline.py \
  --case t2-no-evidence --repeats 1 --repeat-start 0 \
  --no-dataset-staging \
  --results-root "$RES" \
  --experiment-file "$RES/experiment.json" \
  --configuration-id "rca2a2d-cf1-$SCENARIO" \
  --configuration-label "RCA-2A.2d CF-1 settlement scenario: $SCENARIO (offline FunctionModel)" \
  > "$EV/cf1d-$SCENARIO-stdout.log" 2>&1
echo "scenario=$SCENARIO cli_exit=$?"
grep -E "\[settlement\]|\[done\]|\[fail\]|\[FAIL\]" "$EV/cf1d-$SCENARIO-stdout.log" | head -4
REAL_TASK=$(grep -oP 'task=\K[0-9a-f-]{36}' "$EV/cf1d-$SCENARIO-stdout.log" | head -1)
if [ -n "$REAL_TASK" ]; then
  .venv/bin/python "$H/collect_evidence.py" "$REAL_TASK" \
    "$RES/t2-no-evidence/repeat0" "$EV/cf1d-$SCENARIO-dbstate.json" 2>/dev/null | tail -1
fi
