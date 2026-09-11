#!/usr/bin/env bash
# Waits for the raw pull to finish, then runs the whole pipeline end to end.
#
# The pull takes hours, so this exists to make the rest of the build start the
# moment it lands rather than whenever someone next checks on it.

set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate

echo "waiting for the ingest to finish"
while pgrep -f "src.ingest.fetch_raw" > /dev/null; do
    sleep 60
done
echo "ingest process has exited at $(date '+%Y-%m-%d %H:%M:%S')"

python - <<'PY'
import json, sys
m = json.load(open('data/raw/_manifest.json'))
done = sum(1 for s in m['slices'].values() if s['complete'])
total = sum(s['rows'] for s in m['slices'].values())
print(f"slices complete: {done}/{len(m['slices'])}, rows: {total}")
if done < len(m['slices']):
    print("ingest did not finish every slice, stopping rather than building on a partial pull")
    sys.exit(1)
PY

echo "=== second live snapshot, to bound the vintage reconstruction caveat ==="
python -u -m src.ingest.mutation_probe --recheck || echo "probe recheck failed, continuing"

echo "=== building the committed sample from the real pull ==="
python scripts/build_sample.py

echo "=== loading the landing table ==="
python -u -m src.ingest.load_landing

echo "=== dbt build ==="
VARS=$(python scripts/config_to_dbt_vars.py --json)
cd dbt/nyc311_warehouse
DBT_PROFILES_DIR=../../dbt ../../.venv/bin/dbt build --exclude comparison --vars "$VARS" 2>&1 | tail -25
cd ../..

echo "=== vintage replay across both incremental strategies ==="
python -u scripts/run_vintage_replay.py

cd dbt/nyc311_warehouse
DBT_PROFILES_DIR=../../dbt ../../.venv/bin/dbt build --select comparison_drift_summary --vars "$VARS" 2>&1 | tail -12
cd ../..

echo "=== reports ==="
python scripts/generate_measure_dictionary.py
python scripts/generate_reports.py

echo "=== pytest ==="
pytest -q

echo "PIPELINE COMPLETE at $(date '+%Y-%m-%d %H:%M:%S')"
