# Progress

Running log of what is built, what is pending, and what needs a decision from
me rather than from the code.

## Status at a glance

| Phase | Scope | State |
|---|---|---|
| 1 | Ingestion, landing table, vintage reconstruction, reconciliation | in progress |
| 2 | Staging, star schema, date dimension, first passing tests | not started |
| 3 | SCD Type 2, append-only vs merge across vintages, drift table | not started |
| 4 | Metrics layer, dictionary, cohort maturity, BI mart, memo, README | not started |

## Decisions made, and why

**Ingestion window is a trailing 12 months, not the 3 years originally planned.**
The API reports 12,951,069 rows for 2023-01-01 to present. Measured throughput
from this machine against the live API, no app token, is roughly 225 rows per
second, so that window is about 15 hours of continuous pulling. I scoped down to
2025-09-01 through the build date, which the API counts at 3,890,842 rows and
which pulls in roughly 5 hours. The window is set in one place,
`config/config.yml` under `ingest.window_start`, so the full window can be run
later without touching any other file. Every headline number in the README and
memo will state the window it was computed over.

**Pagination sorts on (created_date, unique_key), not unique_key alone.**
A keyset walk needs a unique sort key and unique_key qualifies, but a request
ordered on unique_key alone does not return inside a 170 second timeout, while
the same request ordered created_date first returns in about 35 seconds. The
pair keeps the walk correct and keeps it fast.

**Page size is 10,000.** Measured: 5k rows ~45s, 10k ~50s, 25k ~103s, 50k does
not return inside 120s. Throughput per row is roughly flat, so the page size is
picked to stay well inside the request timeout. A timed out page costs a full
retry, which is the worst outcome on a throttled tier.

**Sequential, not parallel.** Measured 4 concurrent workers at 259 rows/sec
against 225 sequential, a 15% gain, because Socrata throttles the anonymous
tier in aggregate rather than per connection. Not worth the extra failure modes
in the resume logic. Recorded here so the decision is visible rather than
assumed.

**JSON over the CSV export.** Both endpoints deliver at the same throttled rate.
The JSON resource endpoint accepts the same SoQL `$where` and `$order` the
keyset walk depends on, which the bulk CSV export path does not, so resumability
and slicing come free.

## Verified against the live API on 2026-08-28

Re-checked rather than taken from the earlier figures. All matched exactly:

- 2020: 2,942,024 rows, 199 complaint types, 17 agencies
- 2023: 3,224,723 rows
- 2025: 3,655,039 rows
- 2023-01-01 to present: 12,951,069 rows
- max(created_date) at check time: 2026-08-27T02:06:28
- Chosen window, 2025-09-01 onward: 3,890,842 rows

Monthly counts for the chosen window, from the API:
2025-09 302,684 | 2025-10 336,612 | 2025-11 304,905 | 2025-12 332,103 |
2026-01 348,511 | 2026-02 334,690 | 2026-03 342,387 | 2026-04 302,190 |
2026-05 331,978 | 2026-06 334,833 | 2026-07 343,000 | 2026-08 276,949 (partial
month, window ends mid-day 2026-08-28)

## Pending

- [ ] Full raw pull to finish, then reconcile landed row counts against the API
      counts above, per month, and record any gap in the README
- [ ] Committed sample derived deterministically from the real raw files
- [ ] Second live snapshot near the end of the build, to bound the vintage
      reconstruction caveat with a measured mutation rate
- [ ] Everything in phases 2 through 4

## Things I need to do myself

- No GitHub repo yet. Local commits only.
  I push it myself.
- A Socrata app token would raise the rate limit and make the full 3 year window
  practical. It is read from `NYC_OPEN_DATA_APP_TOKEN` and never committed. The
  pipeline runs without one, just slower.
