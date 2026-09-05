"""Replay the vintage sequence through both incremental models.

Run:  python scripts/run_vintage_replay.py

For each vintage in order this invokes a real dbt incremental run, once for the
append only model and once for the merge model, with the vintage cutoff and the
previous cutoff passed as vars. Nothing is simulated in Python: the tables are
built by dbt's own incremental machinery, so the comparison is between two
strategies as dbt actually implements them rather than between two hand written
queries that only resemble them.

After each vintage the state of both tables is measured and appended to
comparison.vintage_drift_log, which is what the drift table in the README is
built from.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config_to_dbt_vars import build_vars  # noqa: E402
from src.config import load_config  # noqa: E402

DRIFT_TABLE = "comparison.vintage_drift_log"

# The dbt executable that belongs to the interpreter running this script. A
# bare "dbt" only resolves when the virtualenv happens to be activated, which
# is true from the shell wrapper and false from make, so it is resolved from
# sys.executable instead and works either way.
DBT_BIN = str(Path(sys.executable).parent / "dbt")


def run_dbt(project_dir: Path, profiles_dir: Path, select: str, dbt_vars: dict,
            full_refresh: bool, target: str | None = None) -> None:
    cmd = [
        DBT_BIN, "run",
        "--project-dir", str(project_dir),
        "--profiles-dir", str(profiles_dir),
        "--select", select,
        "--vars", json.dumps(dbt_vars),
    ]
    if target:
        cmd += ["--target", target]
    if full_refresh:
        cmd.append("--full-refresh")
    # Run from inside the dbt project, because the duckdb path in profiles.yml
    # is written relative to that directory so the repo works as cloned. dbt
    # resolves it against the working directory rather than against
    # --project-dir, so invoking this from the repo root would look for the
    # database two levels above the repo.
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(project_dir))
    if result.returncode != 0:
        print(result.stdout[-4000:])
        print(result.stderr[-2000:])
        raise SystemExit(f"dbt run failed for {select} at vars {dbt_vars}")


def measure(con: duckdb.DuckDBPyConnection, vintage: str, seq: int) -> dict:
    """Snapshot both tables as they stand after this vintage.

    Truth is the merge table's own view of this vintage, because both models
    saw exactly the same rows: whatever merge holds now is what a correctly
    merged pipeline knows at this instant. The append only table is scored
    against it.
    """
    stats = {}
    for label, table in (("append_only", "comparison.fct_requests_append_only"),
                         ("merge", "comparison.fct_requests_merge")):
        row = con.execute(f"""
            select
                count(*)                                            as row_count,
                count(distinct request_id)                          as distinct_requests,
                sum(case when is_closed_at_vintage then 1 else 0 end) as closed_count,
                avg(days_to_close_at_vintage)                       as avg_days_to_close
            from {table}
        """).fetchone()
        stats[label] = {
            "row_count": row[0],
            "distinct_requests": row[1],
            "closed_count": row[2] or 0,
            "avg_days_to_close": float(row[3]) if row[3] is not None else None,
        }

    # rows where the two tables disagree about the state of the same request
    disagreements = con.execute("""
        select count(*)
        from comparison.fct_requests_append_only a
        join comparison.fct_requests_merge m using (request_id)
        where a.is_closed_at_vintage is distinct from m.is_closed_at_vintage
    """).fetchone()[0]

    missed_closures = con.execute("""
        select count(*)
        from comparison.fct_requests_append_only a
        join comparison.fct_requests_merge m using (request_id)
        where m.is_closed_at_vintage and not a.is_closed_at_vintage
    """).fetchone()[0]

    return {
        "vintage_seq": seq,
        "vintage_date": vintage,
        "append_row_count": stats["append_only"]["row_count"],
        "append_distinct_requests": stats["append_only"]["distinct_requests"],
        "append_closed_count": stats["append_only"]["closed_count"],
        "append_avg_days_to_close": stats["append_only"]["avg_days_to_close"],
        "merge_row_count": stats["merge"]["row_count"],
        "merge_distinct_requests": stats["merge"]["distinct_requests"],
        "merge_closed_count": stats["merge"]["closed_count"],
        "merge_avg_days_to_close": stats["merge"]["avg_days_to_close"],
        "rows_disagreeing": disagreements,
        "closures_missed_by_append": missed_closures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample",
        action="store_true",
        help="replay against the sample warehouse using the devsample dbt target",
    )
    args = parser.parse_args()

    cfg = load_config()
    project_dir = (cfg.repo_root / cfg["dbt"]["project_dir"]).resolve()
    profiles_dir = (cfg.repo_root / cfg["dbt"]["profiles_dir"]).resolve()
    db_path = cfg.path("sample_db" if args.sample else "warehouse_db")
    target = "devsample" if args.sample else None

    base_vars = build_vars(cfg)

    con = duckdb.connect(str(db_path))
    vintages = con.execute("""
        select cast(vintage_date as varchar), cast(vintage_cutoff_at as varchar), vintage_seq
        from intermediate.int_vintage_dates
        order by vintage_seq
    """).fetchall()
    con.close()

    if not vintages:
        print("no vintages found, run the base models first")
        return 1

    print(f"replaying {len(vintages)} vintages through both incremental models")

    results = []
    previous_cutoff = None
    for vintage_date, cutoff_at, seq in vintages:
        run_vars = dict(base_vars)
        run_vars["vintage_cutoff"] = cutoff_at
        if previous_cutoff:
            run_vars["previous_cutoff"] = previous_cutoff

        first = seq == 1
        run_dbt(
            project_dir, profiles_dir,
            "int_vintage_source fct_requests_append_only fct_requests_merge",
            run_vars, full_refresh=first, target=target,
        )

        con = duckdb.connect(str(db_path))
        stats = measure(con, vintage_date, seq)
        con.close()

        results.append(stats)
        print(
            f"  vintage {vintage_date}: "
            f"append {stats['append_row_count']} rows / {stats['append_closed_count']} closed, "
            f"merge {stats['merge_row_count']} rows / {stats['merge_closed_count']} closed, "
            f"missed closures {stats['closures_missed_by_append']}",
            flush=True,
        )
        previous_cutoff = cutoff_at

    con = duckdb.connect(str(db_path))
    con.execute("CREATE SCHEMA IF NOT EXISTS comparison")
    con.execute(f"DROP TABLE IF EXISTS {DRIFT_TABLE}")
    con.execute(f"""
        CREATE TABLE {DRIFT_TABLE} (
            vintage_seq INTEGER,
            vintage_date DATE,
            append_row_count BIGINT,
            append_distinct_requests BIGINT,
            append_closed_count BIGINT,
            append_avg_days_to_close DOUBLE,
            merge_row_count BIGINT,
            merge_distinct_requests BIGINT,
            merge_closed_count BIGINT,
            merge_avg_days_to_close DOUBLE,
            rows_disagreeing BIGINT,
            closures_missed_by_append BIGINT
        )
    """)
    con.executemany(
        f"INSERT INTO {DRIFT_TABLE} VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [tuple(r.values()) for r in results],
    )
    con.close()

    print(f"wrote {len(results)} rows to {DRIFT_TABLE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
