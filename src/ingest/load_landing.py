"""Load the raw NDJSON pulls into the DuckDB landing table.

Run:  python -m src.ingest.load_landing [--sample]

The landing table is an append log, not a snapshot. Its grain is
(unique_key, _ingested_at): if the same request is pulled again in a later
fetch, both versions sit in the table and the later one does not overwrite the
earlier one. Everything downstream that wants "the current state of a request"
has to say so explicitly by picking the latest ingestion per key, which is the
point. A landing table that silently keeps only the newest row hides exactly
the restatement this project is built to measure.

Every column lands as VARCHAR, exactly as the API delivered it. Typing and
cleaning happen in the staging models, so a parse failure is a visible test
failure rather than a row that vanished during ingestion.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.config import load_config  # noqa: E402

LANDING_SCHEMA = "raw"
LANDING_TABLE = "service_requests_landing"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="store_true", help="load data/sample instead of data/raw")
    args = parser.parse_args()

    cfg = load_config()
    src_dir = cfg.path("sample_dir") if args.sample else cfg.path("raw_dir")
    files = sorted(src_dir.glob("requests_*.ndjson.gz"))
    if not files:
        print(f"no raw files found in {src_dir}, run the fetch first")
        return 1

    columns = cfg["ingest"]["columns"]
    db_path = cfg.path("sample_db") if args.sample else cfg.path("warehouse_db")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(db_path))
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {LANDING_SCHEMA}")

    # every source column plus the ingestion stamp, all as VARCHAR
    all_cols = list(columns) + ["_ingested_at"]
    col_defs = ",\n    ".join(f'"{c}" VARCHAR' for c in all_cols)
    con.execute(f"DROP TABLE IF EXISTS {LANDING_SCHEMA}.{LANDING_TABLE}")
    con.execute(f"CREATE TABLE {LANDING_SCHEMA}.{LANDING_TABLE} (\n    {col_defs}\n)")

    # read_json needs an explicit column map, otherwise a month whose slice
    # happens to hold only nulls for a column infers a different type and the
    # union across files fails
    json_cols = "{" + ", ".join(f"'{c}': 'VARCHAR'" for c in all_cols) + "}"
    select_list = ",\n           ".join(f'"{c}"' for c in all_cols)

    globs = [str(f) for f in files]
    con.execute(
        f"""
        INSERT INTO {LANDING_SCHEMA}.{LANDING_TABLE}
        SELECT {select_list}
        FROM read_json(?, columns = {json_cols}, format = 'newline_delimited')
        """,
        [globs],
    )

    total = con.execute(f"SELECT count(*) FROM {LANDING_SCHEMA}.{LANDING_TABLE}").fetchone()[0]
    distinct = con.execute(
        f"SELECT count(DISTINCT unique_key) FROM {LANDING_SCHEMA}.{LANDING_TABLE}"
    ).fetchone()[0]

    per_file = con.execute(
        f"""
        SELECT substr(created_date, 1, 7) AS month, count(*) AS rows
        FROM {LANDING_SCHEMA}.{LANDING_TABLE}
        GROUP BY 1 ORDER BY 1
        """
    ).fetchall()

    print(f"loaded {total} rows, {distinct} distinct unique_key, from {len(files)} files")
    for month, rows in per_file:
        print(f"  {month}: {rows}")

    # reconcile against what the fetch manifest says it wrote, so a partial or
    # corrupted file shows up here rather than three models downstream
    manifest_path = src_dir / "_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        fetched = sum(s["rows"] for s in manifest["slices"].values())
        status = "tie out" if fetched == total else "MISMATCH"
        print(f"manifest rows {fetched} vs landed rows {total}: {status}")
        if fetched != total:
            return 2

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
