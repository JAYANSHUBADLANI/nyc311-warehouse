"""Render every number that appears in the README and the memo.

Run:  python scripts/generate_reports.py

Nothing in the written documents is typed by hand. Each table here is queried
out of the warehouse and written to reports/generated as markdown, and the
prose files reference those files rather than restating their contents from
memory. That is the only way to keep a claim in a README honest across a
rebuild.

Output is deterministic: every query has an explicit ORDER BY, floats are
formatted to a fixed number of places, and nothing reads the wall clock.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config  # noqa: E402


def fmt(value, places: int = 2) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:,.{places}f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |"]
    out.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)


def has_table(con, name: str) -> bool:
    schema, _, tbl = name.partition(".")
    return bool(
        con.execute(
            """
            select 1 from information_schema.tables
            where lower(table_schema) = lower(?) and lower(table_name) = lower(?)
            """,
            [schema, tbl],
        ).fetchone()
    )


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f"  wrote {path}")


def report_reconciliation(con, out_dir: Path) -> None:
    rows = con.execute("""
        select stage, description, row_count, delta_from_previous
        from marts.dq_exclusion_ledger
        order by step, stage
    """).fetchall()
    body = table(
        ["Stage", "What it is", "Rows", "Change"],
        [[r[0], r[1], fmt(r[2]), fmt(r[3]) if r[3] is not None else ""] for r in rows],
    )
    write(
        out_dir / "reconciliation.md",
        "# Row count reconciliation\n\n"
        "Every row that entered the landing table is accounted for: either it "
        "reached the fact table or it is named in a quarantine reason below. "
        "The residual line must be zero, and `assert_ledger_reconciles` fails "
        "the build if it is not.\n\n" + body + "\n",
    )


def report_drift(con, out_dir: Path) -> None:
    if not has_table(con, "comparison.comparison_drift_summary"):
        print("  comparison_drift_summary missing, skipping drift report")
        return

    rows = con.execute("""
        select vintage_date, append_row_count, merge_row_count,
               append_closed_count, merge_closed_count, closures_missed_by_append,
               share_of_closures_missed, append_closure_rate, merge_closure_rate,
               closure_rate_error, append_avg_days_to_close, merge_avg_days_to_close,
               avg_days_error, avg_days_error_pct
        from comparison.comparison_drift_summary
        order by vintage_seq
    """).fetchall()

    body = table(
        ["Vintage", "Rows append", "Rows merge", "Closed append", "Closed merge",
         "Closures missed", "Missed %", "Closure rate append", "Closure rate merge",
         "Rate error", "Mean days append", "Mean days merge", "Days error", "Days error %"],
        [[
            str(r[0]), fmt(r[1]), fmt(r[2]), fmt(r[3]), fmt(r[4]), fmt(r[5]),
            fmt(100 * r[6], 2) + "%" if r[6] is not None else "n/a",
            fmt(r[7], 4), fmt(r[8], 4), fmt(r[9], 4),
            fmt(r[10], 3), fmt(r[11], 3), fmt(r[12], 3),
            fmt(100 * r[13], 1) + "%" if r[13] is not None else "n/a",
        ] for r in rows],
    )

    worst = con.execute("""
        select vintage_date, closures_missed_by_append, share_of_closures_missed,
               closure_rate_error, avg_days_error, avg_days_error_pct
        from comparison.comparison_drift_summary
        order by share_of_closures_missed desc nulls last
        limit 1
    """).fetchone()

    final = con.execute("""
        select vintage_date, closures_missed_by_append, share_of_closures_missed,
               append_closure_rate, merge_closure_rate, closure_rate_error,
               append_avg_days_to_close, merge_avg_days_to_close, avg_days_error_pct
        from comparison.comparison_drift_summary
        order by vintage_seq desc
        limit 1
    """).fetchone()

    prose = []
    if final:
        prose.append(
            f"At the final vintage ({final[0]}) the append only table was unaware of "
            f"{fmt(final[1])} closures that a correctly merged table held, which is "
            f"{fmt(100 * final[2], 2)}% of all the closures known at that point. It would "
            f"have published a closure rate of {fmt(final[3], 4)} against the correct "
            f"{fmt(final[4], 4)}, and a mean resolution time of {fmt(final[6], 2)} days "
            f"against the correct {fmt(final[7], 2)} days, understating it by "
            f"{fmt(abs(100 * final[8]), 1)}%."
        )
    if worst:
        prose.append(
            f"The worst vintage was {worst[0]}, where {fmt(100 * worst[2], 2)}% of known "
            f"closures were missing from the append only table."
        )

    write(
        out_dir / "drift_table.md",
        "# Append only versus merge, by vintage\n\n"
        "Both tables were built by dbt's own incremental machinery, fed byte for "
        "byte the same source rows at the same instants. The only difference "
        "between them is the incremental strategy.\n\n"
        "That append only misses restatement is true by construction and is not "
        "presented as a discovery. The measured quantities below, how large the "
        "error is and how it behaves as vintages accumulate, are the finding.\n\n"
        + body + "\n\n" + "\n\n".join(prose) + "\n",
    )


def report_cohort_maturity(con, out_dir: Path) -> None:
    rows = con.execute("""
        select cohort_month, cohort_size, cohort_age_days_at_build, is_cohort_mature,
               closure_rate_so_far, naive_mean_days_to_close, matured_mean_days_to_close,
               naive_understatement_days, naive_understatement_pct,
               unresolved_share_at_maturity
        from marts.mart_cohort_maturity
        order by cohort_month
    """).fetchall()

    body = table(
        ["Cohort", "Requests", "Age at build (days)", "Mature", "Closed so far",
         "Naive mean days", "Corrected mean days", "Gap (days)", "Gap %", "Unresolved at 90d"],
        [[
            str(r[0]), fmt(r[1]), fmt(r[2], 1), "yes" if r[3] else "no",
            fmt(100 * r[4], 1) + "%" if r[4] is not None else "n/a",
            fmt(r[5], 2), fmt(r[6], 2), fmt(r[7], 2),
            fmt(100 * r[8], 1) + "%" if r[8] is not None else "n/a",
            fmt(100 * r[9], 1) + "%" if r[9] is not None else "n/a",
        ] for r in rows],
    )

    write(
        out_dir / "cohort_maturity.md",
        "# Cohort maturity: the naive series next to the corrected one\n\n"
        "The naive mean is computed over closed requests only, which is what a "
        "pipeline publishes if nobody thinks about censoring. The corrected mean "
        "observes every cohort for the same fixed window and ignores closures "
        "after it, so cohorts are comparable regardless of age.\n\n"
        "The unresolved column is the honest companion to the corrected mean: it "
        "is the share of the cohort the correction truncated. A fast corrected "
        "mean sitting next to a high unresolved share does not mean fast.\n\n"
        + body + "\n",
    )


def report_agency_performance(con, out_dir: Path) -> None:
    rows = con.execute("""
        select
            a.agency_key,
            max(ag.agency_name)                                  as agency_name,
            sum(a.request_volume)                                as requests,
            sum(a.closed_volume)                                 as closed,
            cast(sum(a.closed_volume) as double)
                / nullif(sum(a.request_volume), 0)               as closure_rate,
            sum(a.mean_days_to_close * a.closed_volume)
                / nullif(sum(a.closed_volume), 0)                as mean_days_naive,
            sum(case when a.is_cohort_mature
                     then a.mean_days_to_close_matured * (a.closure_rate_at_maturity * a.request_volume)
                end)
                / nullif(sum(case when a.is_cohort_mature
                     then a.closure_rate_at_maturity * a.request_volume end), 0)
                                                                 as mean_days_matured,
            sum(a.backlog_open_count)                            as backlog
        from marts.mart_agency_month a
        left join marts.dim_agency ag on ag.agency_key = a.agency_key
        group by 1
        having sum(a.request_volume) >= 1000
        order by requests desc
        limit 15
    """).fetchall()

    body = table(
        ["Agency", "Name", "Requests", "Closed", "Closure rate",
         "Mean days, naive", "Mean days, corrected", "Open at build"],
        [[
            str(r[0]), (r[1] or "")[:38], fmt(r[2]), fmt(r[3]),
            fmt(100 * r[4], 1) + "%" if r[4] is not None else "n/a",
            fmt(r[5], 2), fmt(r[6], 2), fmt(r[7]),
        ] for r in rows],
    )

    write(
        out_dir / "agency_performance.md",
        "# Resolution speed by agency\n\n"
        "Agencies with at least 1,000 requests in the window, ordered by volume. "
        "Means are rebuilt from their components rather than averaged across "
        "months, because averaging a ratio of ratios weights a quiet month the "
        "same as a busy one.\n\n"
        "The two mean columns are different quantities and the gap between them "
        "is the censoring bias for that agency, not a data problem.\n\n"
        + body + "\n",
    )


def report_complaint_type_drift(con, out_dir: Path) -> None:
    versions = con.execute("""
        select count(*) from marts.dim_complaint_type where not is_unknown_member
    """).fetchone()[0]
    natural_keys = con.execute("""
        select count(distinct complaint_type || '|' || coalesce(descriptor, ''))
        from marts.dim_complaint_type where not is_unknown_member
    """).fetchone()[0]
    multi = con.execute("""
        select complaint_type, descriptor, count(*) as versions,
               min(valid_from_vintage_date) as first_seen,
               max(valid_to_vintage_date)   as last_seen,
               count(distinct owning_agency_code) as distinct_owners
        from marts.dim_complaint_type
        where not is_unknown_member
        group by 1, 2
        having count(*) > 1
        order by versions desc, complaint_type, descriptor
        limit 20
    """).fetchall()

    body = table(
        ["Complaint type", "Descriptor", "Versions", "First vintage", "Last vintage", "Distinct owners"],
        [[str(r[0])[:34], str(r[1])[:34], fmt(r[2]), str(r[3]), str(r[4]), fmt(r[5])] for r in multi],
    )

    write(
        out_dir / "complaint_type_drift.md",
        "# Complaint type dimension: observed drift\n\n"
        f"The dimension holds {fmt(versions)} versions across {fmt(natural_keys)} "
        "distinct complaint type and descriptor pairs. A pair with more than one "
        "version either changed owning agency or fell out of use and came back.\n\n"
        "Pairs with the most versions:\n\n" + body + "\n",
    )


def export_bi_mart(con, cfg) -> None:
    out_dir = cfg.path("bi_mart_dir")
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "nyc311_bi_mart.csv"
    parquet_path = out_dir / "nyc311_bi_mart.parquet"

    # explicit ORDER BY so two runs write byte identical files
    order = "order by cohort_month, agency_code, complaint_type, borough"
    con.execute(f"COPY (SELECT * FROM marts.mart_bi_wide {order}) TO '{csv_path}' (FORMAT CSV, HEADER)")
    con.execute(f"COPY (SELECT * FROM marts.mart_bi_wide {order}) TO '{parquet_path}' (FORMAT PARQUET)")

    rows = con.execute("select count(*) from marts.mart_bi_wide").fetchone()[0]
    print(f"  wrote {csv_path} ({rows:,} rows, {csv_path.stat().st_size / 1024:.0f} KB)")
    print(f"  wrote {parquet_path} ({parquet_path.stat().st_size / 1024:.0f} KB)")


def main() -> int:
    cfg = load_config()
    db_path = cfg.path("warehouse_db")
    if not db_path.exists():
        print(f"no warehouse at {db_path}, run make build first")
        return 1

    out_dir = cfg.repo_root / "reports" / "generated"
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        report_reconciliation(con, out_dir)
        report_cohort_maturity(con, out_dir)
        report_agency_performance(con, out_dir)
        report_complaint_type_drift(con, out_dir)
        report_drift(con, out_dir)
        export_bi_mart(con, cfg)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
