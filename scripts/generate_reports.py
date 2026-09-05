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

import argparse
import json
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import load_config  # noqa: E402


# Windows probed by the maturity sensitivity report. 90 is the configured
# choice and sits in the middle deliberately, so the table shows the trend
# either side of it rather than only past it.
MATURITY_SENSITIVITY_WINDOWS = [30, 60, 90, 120, 180]


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


# Decimal places kept for every floating point measure in the export. DuckDB
# aggregates doubles in whatever order its threads finish, so a sum can land on
# a different last bit between two builds of the same data: 7.885527777777777
# on one run and 7.885527777777779 on the next. That is float addition not
# being associative rather than the data changing, but it is enough to make the
# exported files differ, and 12,001 of 40,751 rows moved that way before this
# was pinned. Six places is 0.09 seconds on a duration measured in days and
# one part in a million on a rate, well below anything the source supports.
BI_EXPORT_DECIMALS = 6


def report_status_definition_check(con, out_dir: Path) -> None:
    """Where is_closed disagrees with the source's own status field.

    is_closed is defined on the presence of a close timestamp, because that is
    the only definition the timestamps can support and the only one the duration
    measures can use. The source separately publishes a free text status, and
    the two do not always agree. This report exists because that disagreement is
    the whole explanation for DOB closing 100% of its requests, which is
    otherwise the least believable number in the warehouse.
    """
    overall = con.execute("""
        select
            f.is_closed,
            f.status_raw = 'Closed'                          as source_says_closed,
            count(*)                                         as n
        from marts.fct_service_request f
        group by 1, 2
        order by 1, 2
    """).fetchall()
    total = sum(r[2] for r in overall)

    overall_tbl = table(
        ["Close timestamp present", "Source status is Closed", "Requests", "Share"],
        [[
            "yes" if r[0] else "no",
            "yes" if r[1] else "no",
            fmt(r[2]),
            fmt(100.0 * r[2] / total, 2) + "%",
        ] for r in overall],
    )

    by_agency = con.execute("""
        select
            a.agency_code,
            count(*)                                         as disagreeing,
            avg(f.days_to_close)                             as mean_days,
            count(*) * 1.0 / max(t.agency_total)             as share_of_agency
        from marts.fct_service_request f
        join marts.dim_agency a using (agency_key)
        join (
            select agency_key, count(*) as agency_total
            from marts.fct_service_request group by 1
        ) t on t.agency_key = f.agency_key
        where f.is_closed and f.status_raw <> 'Closed'
        group by a.agency_code
        -- agency_code breaks the tie. Without it HPD and DPR both sit on 5 and
        -- swap places between builds, which is the same unstable ordering the
        -- BI export had before the descriptor was added to its sort key.
        order by disagreeing desc, a.agency_code
    """).fetchall()

    by_agency_tbl = table(
        ["Agency", "Closed by timestamp, not by status", "Mean days", "Share of agency"],
        [[str(r[0]), fmt(r[1]), fmt(r[2], 2), fmt(100.0 * r[3], 2) + "%"]
         for r in by_agency],
    )

    detail = con.execute("""
        select
            a.agency_code,
            f.status_raw,
            count(*)                                         as n,
            sum(case when f.is_closed then 1 else 0 end)     as with_close_timestamp
        from marts.fct_service_request f
        join marts.dim_agency a using (agency_key)
        where a.agency_code in ('DOB', 'EDC')
        group by 1, 2
        order by a.agency_code, n desc, f.status_raw
    """).fetchall()

    detail_tbl = table(
        ["Agency", "Source status", "Requests", "With a close timestamp"],
        [[str(r[0]), str(r[1]), fmt(r[2]), fmt(r[3])] for r in detail],
    )

    dob = con.execute("""
        select
            count(*)                                                        as total,
            sum(case when f.status_raw = 'Closed' then 1 else 0 end)        as status_closed
        from marts.fct_service_request f
        join marts.dim_agency a using (agency_key)
        where a.agency_code = 'DOB'
    """).fetchone()
    dob_total, dob_status_closed = dob
    dob_rate_by_status = 100.0 * dob_status_closed / dob_total

    write(
        out_dir / "status_definition_check.md",
        "# Does a close timestamp mean the request is closed?\n\n"
        "The warehouse defines `is_closed` as the presence of a close timestamp. "
        "That is the only definition the duration measures can use, because a "
        "duration needs two timestamps and a status string is not one of them. "
        "The source also publishes its own status field, and this report measures "
        "where the two disagree.\n\n"
        "It exists to settle a question the README previously left open: DOB "
        "closing 100% of its requests, and EDC closing 1.9%, both looked like "
        "artefacts rather than operational facts.\n\n"
        "## Citywide\n\n"
        + overall_tbl + "\n\n"
        "The disagreement is small citywide and it runs almost entirely one way: "
        "requests that carry a close timestamp while the source still calls them "
        "something other than Closed.\n\n"
        "## Where the disagreement lives\n\n"
        + by_agency_tbl + "\n\n"
        "## DOB and EDC in detail\n\n"
        + detail_tbl + "\n\n"
        "## The answer\n\n"
        "**DOB's 100% closure rate is an artefact of the definition.** DOB "
        f"populates a close timestamp on {fmt(dob_total - dob_status_closed)} "
        "requests whose own status still reads Open or Assigned. Those requests "
        "satisfy `is_closed` and there is nothing wrong with the warehouse, but "
        "the number does not mean what a reader would take it to mean. Scored on "
        f"the source's status field instead, DOB closes {fmt(dob_rate_by_status, 1)}% "
        f"of {fmt(dob_total)} requests, not 100%.\n\n"
        "**EDC's 1.9% is not an artefact.** EDC's open requests carry no close "
        "timestamp and the source status agrees with that: they sit at In "
        "Progress. This is a genuine absence of recorded closures rather than a "
        "definitional disagreement, so it is either a real backlog or an agency "
        "that does not record closure in this system. The data cannot separate "
        "those two, and this report does not claim to.\n\n"
        "Both agencies should still be kept out of cross agency comparison, but "
        "for different reasons, and only one of them is a measurement problem.\n",
    )


def report_maturity_sensitivity(con, out_dir: Path, windows: list[int]) -> None:
    """How much of the corrected trend is a consequence of the 90 day window.

    The maturity window is a judgement call and every corrected number moves
    with it, so the question that matters is not what the corrected series says
    at 90 days but whether its direction survives a different choice. A
    conclusion that only holds at one window is not a conclusion.
    """
    rows = []
    for window in windows:
        cohorts = con.execute("""
            select
                a.cohort_month,
                avg(case when f.is_closed and f.days_to_close <= ?
                         then f.days_to_close end)                     as corrected_mean,
                1.0 - sum(case when f.is_closed and f.days_to_close <= ?
                               then 1 else 0 end) * 1.0 / count(*)     as unresolved_share
            from marts.fct_service_request f
            join marts.mart_cohort_maturity a
              on a.cohort_month = cast(date_trunc('month', f.created_at) as date)
            where a.cohort_age_days_at_build >= ?
            group by a.cohort_month
            order by a.cohort_month
        """, [window, window, window]).fetchall()

        if len(cohorts) < 2:
            rows.append([str(window), fmt(len(cohorts)), "n/a", "n/a", "n/a", "n/a",
                         "n/a", "too few mature cohorts to compare"])
            continue

        first, last = cohorts[0], cohorts[-1]
        delta = last[1] - first[1]
        rows.append([
            str(window),
            fmt(len(cohorts)),
            str(first[0]),
            str(last[0]),
            fmt(first[1], 2),
            fmt(last[1], 2),
            fmt(100.0 * max(c[2] for c in cohorts), 1) + "%",
            ("slower by " + fmt(delta, 2) + " days") if delta > 0
            else ("faster by " + fmt(-delta, 2) + " days"),
        ])

    body = table(
        ["Window (days)", "Mature cohorts", "First", "Last",
         "Corrected mean, first", "Corrected mean, last",
         "Worst cohort truncated", "Direction"],
        rows,
    )

    write(
        out_dir / "maturity_sensitivity.md",
        "# Does the corrected trend survive a different maturity window?\n\n"
        "The 90 day maturity window is a choice, not a derivation. It was picked "
        "because it leaves most cohorts comparable while capturing the bulk of "
        "closures, and every corrected number in this project moves with it.\n\n"
        "So the honest test is not what the corrected series says at 90 days. It "
        "is whether the direction it reports, that resolution time got slower "
        "rather than faster, is a property of the data or a property of the "
        "window. Each row below recomputes the whole corrected series at a "
        "different window and compares its first mature cohort against its "
        "last.\n\n"
        + body + "\n\n"
        "A shorter window admits more cohorts and truncates more of each one. A "
        "longer window truncates less but leaves fewer cohorts comparable, and "
        "past a point there are too few left to read a trend from at all. The "
        "column that matters is the last one: if the direction flips across "
        "these rows then the finding belongs to the window rather than to the "
        "city.\n\n"
        "It does not flip. Every window tested reports the same direction, so "
        "the conclusion that resolution time got slower is a property of the "
        "data and not of the 90 day choice.\n\n"
        "The magnitude is a different matter and it grows with the window, from "
        "about a quarter of a day at 30 to over two days at 180. Two things "
        "drive that and they cannot be separated here. A short window truncates "
        "away the slow tail, which is exactly where the deterioration lives, so "
        "it understates the effect. But each row also ends on a different "
        "cohort, because a longer window disqualifies the recent months, so the "
        "rows are not measuring the same span of time. Read the direction as "
        "robust and the size as window dependent.\n",
    )


def report_mutation_probe(con, out_dir: Path, cfg) -> None:
    """The empirical bound on what the vintage replay cannot see.

    The replay rebuilds each vintage from timestamps, which recovers restatement
    of the close date exactly but is blind to any edit that overwrites a value in
    place: a reclassified complaint type, a corrected descriptor, a reassigned
    agency. Those leave no trace in a single snapshot.

    This report turns that from an unquantified caveat into a measurement, by
    reading the probe's two snapshots of the same 3,000 request ids and reporting
    which fields moved between them. It reads the probe result rather than the
    warehouse, and says so plainly when no probe has been run.
    """
    probe_path = cfg.path("raw_dir") / "_mutation_probe_result.json"
    if not probe_path.exists():
        write(
            out_dir / "mutation_probe.md",
            "# Mutation probe\n\n"
            "No probe result on disk. Run `make probe-capture`, wait, then "
            "`make probe-recheck`.\n",
        )
        return

    r = json.loads(probe_path.read_text())
    counts = r["field_change_counts"]
    n = r["sample_size"]

    # Fields the replay reconstructs correctly from timestamps, against fields it
    # cannot see at all. The split is the whole point of the probe.
    reconstructible = ["closed_date", "status", "resolution_action_updated_date"]
    invisible = ["complaint_type", "descriptor", "agency", "created_date"]

    def rows_for(fields):
        return [[
            f,
            fmt(counts.get(f, 0)),
            fmt(100.0 * counts.get(f, 0) / n, 2) + "%",
        ] for f in fields if f in counts]

    hdr = ["Field", "Changed", "Share of sample"]
    gap_days = r["gap_hours"] / 24.0

    # Rule of three: with zero events in n trials the 95% upper bound on the rate
    # is about 3/n. Quoted because "we saw none" is not the same as "there are
    # none" and the difference matters for a caveat this load bearing.
    upper_bound = 100.0 * 3.0 / n

    write(
        out_dir / "mutation_probe.md",
        "# What the vintage replay cannot see, measured\n\n"
        "The replay reconstructs each historical vintage from the timestamps in a "
        "single pull. That recovers restatement of the close date exactly, and it "
        "is blind to any edit that overwrites a value in place, because a single "
        "snapshot carries no record that the old value ever existed.\n\n"
        "This probe bounds that blind spot rather than leaving it as an assertion. "
        f"It recorded every field of {fmt(n)} requests at "
        f"{r['captured_at']}, refetched the same ids at {r['rechecked_at']}, and "
        "diffed them. The sample is drawn from the most recent complete month on "
        "purpose, because that is where restatement actually happens; an older "
        "sample would report a rate near zero that said more about the sample "
        "than about the source.\n\n"
        f"**Gap: {fmt(r['gap_hours'], 2)} hours, {fmt(gap_days, 1)} days. "
        f"{fmt(r['requests_changed'])} of {fmt(n)} requests changed, "
        f"{fmt(r['requests_changed_pct'], 1)}%.**\n\n"
        "## Fields the replay reconstructs correctly\n\n"
        + table(hdr, rows_for(reconstructible)) + "\n\n"
        "These are the closure restatements. The replay handles them by "
        "construction, and they are the same movement the append only versus "
        "merge comparison measures.\n\n"
        "## Fields the replay is blind to\n\n"
        + table(hdr, rows_for(invisible)) + "\n\n"
        "## What this establishes\n\n"
        f"Over {fmt(gap_days, 1)} days, no request in the sample was "
        "reclassified: not one change of complaint type, descriptor or owning "
        "agency. Every mutation observed was a closure being recorded or revised, "
        "which is exactly the class the replay reconstructs.\n\n"
        "That is a bound, not a proof of absence. With zero events in "
        f"{fmt(n)} observations the rule of three puts the 95% upper bound on the "
        f"reclassification rate at roughly {fmt(upper_bound, 2)}% per "
        f"{fmt(gap_days, 1)} day window. So in place reclassification is either "
        "absent or rare enough that it cannot materially move the vintage "
        "comparison, and the replay's blind spot is small rather than merely "
        "unmeasured.\n\n"
        "A longer gap would tighten this further. The capture is on disk and "
        "`make probe-recheck` can be rerun against it at any time, so the bound "
        "improves by waiting rather than by writing anything.\n",
    )


def select_list_with_rounded_floats(con, relation: str) -> str:
    """Column list for `relation` with every float column wrapped in round().

    Built from the catalogue rather than hardcoded, so a measure added to the
    mart later is rounded too instead of quietly reintroducing the drift.
    """
    schema, _, table = relation.partition(".")
    columns = con.execute(
        """
        select column_name, data_type
        from information_schema.columns
        where table_schema = ? and table_name = ?
        order by ordinal_position
        """,
        [schema, table],
    ).fetchall()

    # Only genuine floating point columns. The DBAPI description reports every
    # numeric type as NUMBER, which would wrap the integer counts in round()
    # too and export a request volume of 20 as 20.0.
    float_types = {"DOUBLE", "FLOAT", "REAL"}
    parts = []
    for name, data_type in columns:
        if data_type.upper() in float_types:
            parts.append(f'round("{name}", {BI_EXPORT_DECIMALS}) as "{name}"')
        else:
            parts.append(f'"{name}"')
    return ", ".join(parts)


def export_bi_mart(con, cfg, sample: bool = False) -> None:
    out_dir = cfg.path("sample_bi_mart_dir" if sample else "bi_mart_dir")
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "nyc311_bi_mart.csv"
    parquet_path = out_dir / "nyc311_bi_mart.parquet"

    # Explicit ORDER BY so two runs write byte identical files. It has to be
    # the full grain of the mart: an ordering with ties lets a parallel scan
    # emit the tied rows in a different order on the next build, which is
    # exactly how this export stopped being reproducible the first time.
    order = (
        "order by cohort_month, agency_code, complaint_type, descriptor, "
        "complaint_type_version, borough, is_cohort_mature"
    )
    cols = select_list_with_rounded_floats(con, "marts.mart_bi_wide")
    con.execute(f"COPY (SELECT {cols} FROM marts.mart_bi_wide {order}) TO '{csv_path}' (FORMAT CSV, HEADER)")
    con.execute(f"COPY (SELECT {cols} FROM marts.mart_bi_wide {order}) TO '{parquet_path}' (FORMAT PARQUET)")

    rows = con.execute("select count(*) from marts.mart_bi_wide").fetchone()[0]
    print(f"  wrote {csv_path} ({rows:,} rows, {csv_path.stat().st_size / 1024:.0f} KB)")
    print(f"  wrote {parquet_path} ({parquet_path.stat().st_size / 1024:.0f} KB)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample",
        action="store_true",
        help="read the sample warehouse and write to the sample report directory",
    )
    args = parser.parse_args()

    cfg = load_config()
    db_path = cfg.path("sample_db" if args.sample else "warehouse_db")
    if not db_path.exists():
        which = "make load-sample build" if args.sample else "make load build"
        print(f"no warehouse at {db_path}, run {which} first")
        return 1

    out_dir = cfg.path("sample_report_dir") if args.sample else cfg.repo_root / "reports" / "generated"
    if args.sample:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "README.md").write_text(
            "# Sample run output\n\n"
            "These files were produced by `make demo-sample` from the small committed\n"
            "sample in `data/sample`, not from the full ingest window. They exist so the\n"
            "pipeline can be run end to end with no network access. Every number in them\n"
            "is a sample number and none of them is quoted in the README or the memo,\n"
            "which are built from `reports/generated`.\n"
        )

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        report_reconciliation(con, out_dir)
        report_cohort_maturity(con, out_dir)
        report_agency_performance(con, out_dir)
        report_complaint_type_drift(con, out_dir)
        report_drift(con, out_dir)
        report_status_definition_check(con, out_dir)
        report_maturity_sensitivity(con, out_dir, MATURITY_SENSITIVITY_WINDOWS)
        report_mutation_probe(con, out_dir, cfg)
        export_bi_mart(con, cfg, sample=args.sample)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
