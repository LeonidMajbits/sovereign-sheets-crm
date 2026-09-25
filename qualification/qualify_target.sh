#!/bin/sh
# Reproducible target run. No live cloud call, credentials or production DB.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUT=${1:?Provide a NEW absolute qualification output directory}
PYTHON=${PYTHON:-python3}
case "$OUT" in /*) ;; *) echo "Output directory must be absolute." >&2; exit 2;; esac
if [ -e "$OUT" ]; then echo "Output path already exists; preserve the previous run." >&2; exit 2; fi
mkdir -p "$OUT"
cd "$HERE"
"$PYTHON" - <<'CHECK'
import platform, sqlite3
print(platform.platform(), sqlite3.sqlite_version)
assert platform.system() == 'Darwin' and platform.machine() == 'arm64', 'Darwin arm64 required'
assert sqlite3.sqlite_version_info >= (3,51,3), 'Python-linked SQLite >=3.51.3 required'
CHECK
"$PYTHON" -m pytest tests -q --junitxml="$OUT/tests.xml" > "$OUT/tests.log" 2>&1
node tests/test_apps_script.js > "$OUT/apps_script.json"
"$PYTHON" qualification/run_matrix.py --require-darwin-arm64 --workers 100 --tenants 10 --operations 50000 --keep-fixtures --output "$OUT/matrix" > "$OUT/matrix.log" 2>&1
FIXTURE=$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1]))["raw_fixture_root"])' "$OUT/matrix/matrix_results.json")
"$PYTHON" qualification/audit_evidence.py --fixture-root "$FIXTURE" --trace "$OUT/matrix/audit_trace.jsonl.gz" --result "$OUT/audit_trace_verification.json" > "$OUT/audit_trace_export.log"
"$PYTHON" qualification/verify_fixture_storage.py --fixture-root "$FIXTURE" --output "$OUT/exact_storage_oracle.json" > "$OUT/exact_storage_oracle.log"
"$PYTHON" qualification/verify_register_trace.py --trace "$OUT/matrix/operation_trace.jsonl.gz" --output "$OUT/register_trace_oracle.json" > "$OUT/register_trace_oracle.log"
"$PYTHON" qualification/run_streaming.py --output "$OUT/streaming" > "$OUT/streaming.log" 2>&1
"$PYTHON" qualification/run_rpc_stress.py --output "$OUT/rpc" > "$OUT/rpc.log" 2>&1
"$PYTHON" qualification/run_adversarial.py --output "$OUT/adversarial" > "$OUT/adversarial.log" 2>&1
"$PYTHON" tools/benchmark_search.py --runs 2 --queries 2000 --common 2000 --output "$OUT/search.json" > "$OUT/search.log" 2>&1
printf '%s\n' 'Target execution complete. Inspect measured gates; simulated Google tests are not live deployment certification.'
