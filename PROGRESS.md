# Progress

Running log of what is built, what is pending, and what needs a decision from
me rather than from the code.

## Status at a glance

| Phase | Scope | State |
|---|---|---|
| 1 | Ingestion, landing table, vintage reconstruction, reconciliation | done, full 12 month pull landed |
| 2 | Staging, star schema, date dimension, first passing tests | done, 47 dbt tests and 7 pytest passing |
| 3 | SCD Type 2, append only vs merge across vintages, drift table | done, 12 real vintages replayed |
| 4 | Metrics layer, dictionary, cohort maturity, BI mart, memo, README | done |

All four phases are complete and every number in the README, the memo and the
dictionary comes from a real run against the real pull.

## The numbers, as built

- 3,890,842 rows landed, 840 quarantined, 3,890,002 in the fact table, residual
  zero. The 840 are all one rule, a close timestamp before the create
  timestamp, which is 0.022% and is real dirt rather than a tuned threshold
- 17 agencies, 1,198 complaint type and descriptor pairs across 1,720 dimension
  versions, 318 pairs with more than one version
- Append only against merge at the final vintage: 483,003 closures missed,
  13.05% of all closures, mean days to close 1.500 against 6.332, understated
  by 76.3%. Zero error at the first vintage, growing monotonically after
- Cohort maturity: naive series falls 7.31 to 1.46 days and reads as an 80%
  improvement, corrected series rises 3.88 to 5.20 over the comparable range.
  The improvement is entirely an artefact of cohort age, and the direction holds
  at every maturity window from 30 to 180 days
- 22,288 requests, 0.57%, carry a close timestamp while the source status still
  says something other than Closed. 17,568 of those are DOB, which is the whole
  explanation for DOB appearing to close 100% of its requests

## Decisions made, and why

**Ingestion window is a trailing 12 months, not the 3 years originally planned.**
The API reports 12,951,069 rows for 2023-01-01 to present. Measured throughput
from this machine against the live API, no app token, is roughly 225 rows per
second, so that window is about 15 hours of continuous pulling. I scoped down to
2025-09-01 onward, which the API counts at 3,890,842 rows and which pulled in a
little over four hours. The window is set in one place, `config/config.yml`
under `ingest.window_start`, so the full window can be run later without
touching any other file.

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
in the resume logic.

**JSON over the CSV export.** Both endpoints deliver at the same throttled rate.
The JSON resource endpoint accepts the same SoQL `$where` and `$order` the
keyset walk depends on, which the bulk CSV export path does not, so resumability
and slicing come free.

**DuckDB runs on one thread.** This is a reproducibility decision, not a
performance one, and it cost about 36 seconds on a build that took half a
minute. Detail in the section below.

## Verified against the live API on 2026-08-28

Re-checked rather than taken on trust:

- 2020: 2,942,024 rows, 199 complaint types, 17 agencies
- 2023: 3,224,723 rows
- 2025: 3,655,039 rows
- 2023-01-01 to present: 12,951,069 rows
- max(created_date) at check time: 2026-08-27T02:06:28
- Chosen window, 2025-09-01 onward: 3,890,842 rows

Monthly counts for the chosen window, from the API, and all twelve landed
complete and matching:
2025-09 302,684 | 2025-10 336,612 | 2025-11 304,905 | 2025-12 332,103 |
2026-01 348,511 | 2026-02 334,690 | 2026-03 342,387 | 2026-04 302,190 |
2026-05 331,978 | 2026-06 334,833 | 2026-07 343,000 | 2026-08 276,949

## Five things I got wrong and had to fix

**dbt was writing to schemas nothing else could find.** Without a
`generate_schema_name` override, dbt prefixes a custom schema with the target
schema, so a model configured into `marts` landed in `main_marts`. Every script
addresses these tables as `marts.x`, which is the name the models themselves
declare, so the replay and the report generator both failed on a catalogue
error. The override makes the warehouse match the names the rest of the project
already uses. This is the bug that stopped the whole thing finishing the first
time and it was one missing macro.

**Three ways of invoking dbt, two of which did not work.** The Makefile passed
its vars inside single quotes, so the shell handed dbt the literal text of the
command substitution instead of running it, and it resolved the script path
after changing directory. The replay script shelled out to a bare `dbt`, which
only resolves when the virtualenv happens to be activated, and ran it from the
repo root, where the relative database path in `profiles.yml` points two levels
above the repo. Only the shell wrapper worked, because it activated the
environment and changed directory first. All three now resolve the interpreter
and the working directory explicitly.

**The BI export had no unique sort key, and the reason was a missing column.**
It was ordered by cohort month, agency, complaint type and borough, which
distinguishes 9,429 of its 40,751 rows. The mart underneath is keyed on the
complaint type surrogate, which resolves a complaint type and descriptor pair,
and the export carried the type but not the descriptor. So it was not merely
unsorted: a filter on one type, borough and month returned four rows identical
in every visible column with different numbers against each, which reads as
duplicate data. Adding the descriptor made all 40,751 rows unique.

**DuckDB's parallel aggregation is not bit reproducible.** Floating point
addition is not associative, so a mean built by four threads lands on a
different last bit depending on which thread finishes first: 7.885527777777777
on one run and 7.885527777777779 on the next. That moved 12,001 of 40,751 rows
between two builds of identical data. Rounding the export to six decimals cut
it to 123 rows, the ones sitting exactly on a rounding boundary, which is the
tell that rounding was treating the symptom. Pinning DuckDB's own thread count
to one fixed it outright. Note that dbt's `threads` setting does not do this:
it limits how many models run at once, not the engine's intra query
parallelism, which has to be set under `settings` in the profile.

**The offline sample run overwrote the real one.** `--sample` changed which
directory was read and nothing else, so it loaded the 6,000 row sample into the
same `data/warehouse.duckdb` holding the full 3.9 million row pull, rebuilt
every model on top of it, and rewrote `reports/generated` with sample numbers in
exactly the same format as the real ones. Anyone running the offline demo after
a full pull would have destroyed both, with nothing on screen to say so, and the
committed evidence would then have disagreed with the README. The `devsample`
profile target existed and was unused, which is what gave the intent away. The
sample path now has its own database and its own output directory, both named in
the config, and I verified the separation by hashing the real warehouse and the
real reports before and after a sample run.

## Verified reproducible

Three consecutive build and report runs produce byte identical output, compared
by SHA-256 across every generated file rather than assumed from the seeding.
The dbt suite was run three times in a row to confirm an intermittent abort
under four threads is gone.

## Pending

- [ ] A second live snapshot weeks after the first. The one I have compares
      3,000 requests across a 2.67 hour gap and found zero changes, which bounds
      same-day churn and essentially nothing else. This is the weakest claim in
      the project and it is a matter of waiting rather than of code
- [x] Run down DOB at 100% closed on 116,287 requests and EDC at 1.9% on 14,260.
      Done, and they turned out to be two different things. DOB records a close
      timestamp on 17,568 requests its own status field still calls Open or
      Assigned, so `is_closed` and the source status disagree and the 100% is a
      definitional artefact; on status it closes 84.9%. EDC's 13,992 open
      requests carry no close timestamp at all and the status agrees with that,
      so its 1.9% is a genuine absence of recorded closures rather than a
      measurement problem. Citywide the disagreement is 22,288 requests, 0.57%,
      and DOB is 79% of it, so nothing else in the warehouse moves. Quantified
      in `reports/generated/status_definition_check.md`
- [x] Sensitivity of the corrected series to the 90 day maturity window. Done,
      recomputed at 30, 60, 90, 120 and 180 days in
      `reports/generated/maturity_sensitivity.md`. The direction survives every
      one of them, so the deterioration is a property of the data rather than of
      the window. The magnitude does not survive, ranging from 0.28 days at 30
      to 2.14 at 180, partly because a short window truncates the slow tail
      where the deterioration lives and partly because a long window disqualifies
      the recent cohorts, so each row ends on a different month. Those two causes
      cannot be separated with one pull and the report says so
- [ ] The full 2023 onward window, which needs an app token to be practical

## Open items for me

- Version control and the push are mine to do by hand. Nothing in the pipeline
  creates a repository or a remote
- A Socrata app token would raise the rate limit and make the full three year
  window practical. It is read from `NYC_OPEN_DATA_APP_TOKEN` and never
  committed. The pipeline runs without one, just slower
