# NYC 311 service request warehouse

I built a local analytical warehouse over New York City's 311 service request
data to answer one question honestly: how fast does each agency actually close
the requests it owns, and how much of any apparent improvement is an artefact
of measuring a cohort that has not finished closing yet.

The warehouse is DuckDB, the transformation layer is dbt, and the ingestion is
plain Python against the Socrata API. Everything runs locally with no cloud
account and no Docker.

The part I care most about is not the star schema. It is the measurement of how
wrong a pipeline gets when it appends new rows and never revisits the old ones,
which is the single most common way a warehouse built on a mutating source
starts lying without anyone noticing.

## The headline result

I built the same fact table twice, once appending only new keys and once
merging on the unique key so restated rows update in place, and replayed twelve
monthly vintages through both. Both were built by dbt's own incremental
machinery and fed byte for byte the same rows at the same instants. The only
difference is the strategy.

At the final vintage, 28 August 2026:

| | Append only | Merge | Error |
| --- | --- | --- | --- |
| Rows | 3,890,002 | 3,890,002 | none |
| Closures known | 3,218,137 | 3,701,140 | **483,003 missing, 13.05% of all closures** |
| Closure rate | 0.8273 | 0.9514 | 12.42 points too low |
| Mean days to close | 1.500 | 6.332 | **4.83 days too fast, understated by 76.3%** |

The row counts are identical, which is the part worth pausing on. Append only
does not lose requests. It captures every new one. What it loses is every
subsequent change to a request it has already seen, and because a 311 request
is created open and closed later, that is almost the entire useful signal. A
dashboard on the append only table would have reported that the city closes
requests in a day and a half. The real figure is four times that.

The error also compounds. It is zero at the first vintage, because nothing has
been restated yet, then grows monotonically:

| Vintage | Closures missed | Missed % | Mean days error % |
| --- | --- | --- | --- |
| 2025-09-30 | 0 | 0.00% | 0.0% |
| 2025-12-31 | 90,119 | 7.63% | -53.9% |
| 2026-03-31 | 237,212 | 11.03% | -67.4% |
| 2026-08-28 | 483,003 | 13.05% | -76.3% |

That an append only model misses restatement is true by construction and I am
not presenting it as a discovery. The finding is the size of the error and its
shape over time: it starts at exactly zero, which is why this class of bug
survives code review and a first week in production, and it is still growing
after a year rather than settling.

The full table is in [reports/generated/drift_table.md](reports/generated/drift_table.md).

## The second result: recent months are not faster

The naive way to report resolution speed is to average the duration of the
requests that have closed. Do that by cohort month and the city looks like it
is improving dramatically:

| Cohort | Naive mean days | Corrected mean days | Unresolved at 90d |
| --- | --- | --- | --- |
| 2025-09 | 7.31 | 3.88 | 4.1% |
| 2025-12 | 8.32 | 4.39 | 4.4% |
| 2026-03 | 6.56 | 5.56 | 4.3% |
| 2026-04 | 5.81 | 5.20 | 4.2% |
| 2026-07 | 3.41 | not mature | |
| 2026-08 | 1.46 | not mature | |

The naive series falls from 7.31 days to 1.46, which reads as a 80% improvement
and would be a good slide. It is an artefact. The August cohort is 27 days
old at the build instant, against a 90 day maturity window, so the only
requests in it that have closed are the fast ones, and the slow ones contribute nothing because they contribute no
duration at all. The corrected series, which observes every cohort for the same
fixed 90 day window and ignores closures after it, moves the other way: from
3.88 days to 5.20 over the comparable range. Resolution time got slower, not
faster.

The two right hand columns are the honest companions to each other. A fast
corrected mean sitting next to a high unresolved share does not mean fast, it
means the correction truncated a lot.

Full table in [reports/generated/cohort_maturity.md](reports/generated/cohort_maturity.md),
by agency in [reports/generated/agency_performance.md](reports/generated/agency_performance.md).

## What I loaded

| | |
| --- | --- |
| Source | NYC Open Data, Socrata dataset `erm2-nwe9` |
| Window | 2025-09-01 to 2026-08-28 |
| Rows landed | 3,890,842 |
| Rows in the fact table | 3,890,002 |
| Quarantined | 840 |
| Agencies | 17 |
| Complaint type and descriptor pairs | 1,198, in 1,720 dimension versions |
| Vintages replayed | 12, monthly |

Nothing is sampled. The 3,890,842 figure is what the API's own count endpoint
reported for that window before the pull started, and it is what landed, per
month, all twelve slices complete.

### Why a trailing twelve months and not three years

I originally scoped 2023-01-01 to present, which the API counts at 12,951,069
rows. Measured throughput from this machine with no app token is roughly 225
rows per second, and it does not improve with concurrency because Socrata
throttles the unauthenticated tier in aggregate rather than per connection: I
measured four workers at 259 rows per second against 225 sequential, a 15% gain
that was not worth the extra failure modes in the resume logic. Three years
would therefore have been about fifteen hours of continuous pulling. Twelve
months is 3,890,842 rows and took a little over four.

What the shorter window still supports: twelve monthly cohorts, of which eight
are fully mature at the 90 day maturity window, real restatement, and genuine
complaint type vocabulary drift. What it gives up: multi-year seasonality, and
the longer dimension history a 2023 start would have shown.

The window is set in one place, `ingest.window_start` in
[config/config.yml](config/config.yml). Changing it and rerunning the ingest is
the only thing needed to run the full three years.

## Row count reconciliation

Every row that entered the landing table is accounted for.

| Stage | Rows | Change |
| --- | --- | --- |
| Landed | 3,890,842 | |
| Deduplicated to current state | 3,890,842 | 0 |
| Quarantined, close timestamp before create timestamp | 840 | |
| Into the fact table | 3,890,002 | -840 |
| Residual | 0 | |

840 rows out of 3,890,842 is a 0.022% failure rate. That is real dirt in the
source, not a tuned threshold: the rule is that a request cannot close before
it was created, the rows that break it are quarantined rather than repaired,
and `assert_ledger_reconciles` fails the build if the residual is not zero.

## What is in the warehouse

Staging cleans and types the raw columns. The star schema is a fact at service
request grain, one row per request, with dimensions for agency, complaint type
and descriptor, geography and date.

**The grain of the fact is one row per service request**, not one per status
change, because the source publishes current state rather than an event log.
NYC 311 reuses the same `unique_key` when a request is reopened and overwrites
its close date, so there is no reopen event to model and no way to recover the
earlier close. That is a property of the source and it is the single largest
constraint on everything downstream.

**The complaint type and descriptor dimension is Type 2.** The vocabulary
genuinely moves: 1,198 pairs across the window produce 1,720 versions, and 318
pairs have more than one version, meaning they changed owning agency or fell
out of use and came back. A fact row joins to the version that was current when
the request was created, not the latest one, and
`assert_scd2_join_uses_version_current_at_creation` fails if that join ever
grabs the wrong version. Two further tests assert that versions never overlap
and that exactly one version per pair is current.

## Tests

`make test` runs 47 dbt data tests, all passing: uniqueness, not null, accepted
values and referential integrity, plus the business rules that actually matter
here, close date before create date, negative durations, coordinates outside
New York, orphan agency codes, the ledger reconciliation and the three SCD Type
2 assertions. `make pytest` runs 7 Python unit tests over the vintage
reconstruction logic against a synthetic fixture.

I did not tune any assertion to get a green suite. The 840 quarantined rows are
the one real data quality failure in the window and they are counted rather
than dropped silently.

## Reproducibility

Two consecutive runs on the same input produce byte identical artefacts. I
checked this by running the build and the reports three times and comparing
SHA-256 of every generated file, rather than assuming the seeding was enough.

Getting there took two fixes worth recording, because both are the kind of
thing that is invisible until someone diffs two runs.

**The BI export had no unique sort key.** It was ordered by cohort month,
agency, complaint type and borough, which distinguishes only 9,429 of its
40,751 rows. The other 31,322 were tied, and a parallel scan emitted tied rows
in a different order on each build. The cause was that the export carried the
complaint type but not the descriptor, while the mart underneath is keyed on
the surrogate that resolves both. So the export was not merely unsorted, it was
showing four rows that were identical in every visible column with different
measures against each. Adding the descriptor made all 40,751 rows unique and
made the ordering total.

**DuckDB's parallel aggregation is not bit reproducible.** Floating point
addition is not associative, so a mean built by four threads lands on a
different last bit depending on which thread finishes first: 7.885527777777777
on one run, 7.885527777777779 on the next. That moved 12,001 of 40,751 rows.
Rounding the exported floats to six decimal places cut it to 123 rows, the ones
sitting exactly on a rounding boundary, which is the tell that rounding treats
the symptom. The fix is to pin DuckDB's own thread count to one in
[dbt/profiles.yml](dbt/profiles.yml), which costs about 36 seconds on a build
that takes half a minute, and buys the guarantee outright. The rounding is kept
as well, since a six decimal duration is 0.09 seconds and nothing in the source
supports more precision than that.

Nothing reads the wall clock. `build_as_of` is pinned to the ingest window end
taken from the ingest manifest, so backlog and maturity figures are computed
against the data that actually landed rather than against whenever dbt happened
to run.

## Running it

```bash
make venv
make fetch
make demo
```

`make fetch` is the slow part, roughly four hours against the throttled
anonymous tier. `make demo` runs load, build, test, replay, reports and pytest
end to end from an empty warehouse once the raw pull is on disk, timed at
1 minute 24 seconds on this machine. That was measured after a `make clean`, so
it includes reloading all 3,890,842 rows from the raw slices and not just
rebuilding the models on top of an existing landing table.

A Socrata app token raises the rate limit. It is read from the environment
variable `NYC_OPEN_DATA_APP_TOKEN` and is never committed. The pipeline runs
without one, just slower.

To run without any network at all, against the committed sample:

```bash
make demo-sample
```

That runs the identical pipeline over a 6,000 row committed sample. It writes to
its own database and to `reports/generated_sample`, and it never touches the
full warehouse or the numbers in `reports/generated` that this README quotes. I
checked that by hashing both before and after a sample run.

The separation is deliberate and it was not there originally. The sample flag
used to change only which directory was read, so running the offline demo after
a full pull replaced 3.9 million rows with the sample and rewrote every
generated report with sample numbers in exactly the same format, leaving the
committed evidence quietly disagreeing with the README. A sample run that
silently overwrites the real results is worse than no sample run at all.

Raw pulls are not in version control. The committed sample is derived
deterministically from the real pull so the repository is reproducible and the
test suite runs offline.

## Vintage reconstruction, and the honest caveat

For a cutoff T, a request created before T whose close date is after T was open
at T, so its state at T rebuilds deterministically from the timestamps. That is
what makes the twelve vintage replay possible from a single pull.

**It only reconstructs the timestamp derived fields.** If a ticket's complaint
type was reclassified, or its descriptor edited, a single snapshot cannot see
it, and the replay will show the current classification at every historical
vintage as though it had always been there. Every vintage in the comparison
above inherits that limitation.

I tried to bound it by snapshotting the live API twice and comparing the
overlap. The result is weak and I would rather say so than dress it up: 3,000
requests re-fetched after a gap of **2.67 hours**, of which 0 changed on any of
the seven fields checked. A 2.67 hour gap is far too short to observe
meaningful reclassification, so what that probe establishes is close to
nothing. It bounds same-day churn and no more. A proper bound needs two
snapshots weeks apart, which is a matter of waiting rather than of code, and
the probe script is in place to do it.

## What this does not cover

No orchestration scheduler. No cloud warehouse. No streaming ingestion. No
access control or row level security. No dashboard: the BI deliverable is the
data half, a wide pre-aggregated table plus the specification of what to put on
it, and [reports/bi_handoff.md](reports/bi_handoff.md) says so in its first
line.

No SLA table per agency and complaint type. On time performance is measured
against a single citywide 30 day target set in the config, which is a real
simplification, because NYC 311 sets targets per agency and complaint type. The
measure dictionary records it as such.

## Where I would push back on this myself

**The single citywide SLA is the weakest number here.** On time performance
against a flat 30 days is not a number I would put in front of an operations
owner without saying in the same breath that the real targets differ by
complaint type. It is in the metrics layer because the layer needs an on time
measure, not because 30 days is defensible.

**The mutation probe does not do the job it was built for.** Covered above. It
is the gap I would most want to close.

**Reopened requests are invisible.** The source overwrites, so a request closed,
reopened and closed again is indistinguishable from one that took that long the
first time, and its measured duration is inflated. Nothing in this warehouse can
separate them, and no amount of modelling fixes a source that does not publish
the event.

**NYPD dominates every citywide aggregate.** 1,709,166 of 3,890,002 requests in
the window, closing at 99.9% in a mean of 0.10 days, which is a different
operational process to HPD taking 9.72 days on housing complaints. Any citywide
mean is mostly one agency's noise complaints. The marts are cut by agency for
that reason and the dictionary repeats the warning on every measure.

**The 90 day maturity window is a choice, not a derivation.** I picked it
because it makes eight of twelve cohorts mature while still capturing the bulk
of closures, and a different window moves every corrected number. I have since
recomputed the whole corrected series at 30, 60, 90, 120 and 180 days, in
[reports/generated/maturity_sensitivity.md](reports/generated/maturity_sensitivity.md).
The direction holds at every one of them, so the finding that resolution time
got slower is not an artefact of the choice. The magnitude is, and it ranges
from a quarter of a day to over two, for two reasons the table separates out.

**DOB's 100% closure rate is a definitional artefact. EDC's 1.9% is not.** This
was an open question and it is now answered, in
[reports/generated/status_definition_check.md](reports/generated/status_definition_check.md).
`is_closed` is defined on the presence of a close timestamp, which is the only
definition a duration measure can use. DOB populates a close timestamp on 17,568
requests whose own status field still reads Open or Assigned, which is 15.1% of
its volume and 79% of the entire citywide disagreement. Scored on the source's
status instead, DOB closes 84.9%, not 100%. EDC is a different thing: its 13,992
open requests carry no close timestamp and the status agrees, sitting at In
Progress, so that is either a real backlog or an agency that does not record
closure here, and the data cannot separate those. Citywide the disagreement is
22,288 requests, 0.57%, so no other number in this project moves because of it.
Both agencies stay out of cross agency comparison, but only one of them is a
measurement problem.

## Layout

```
config/           config.yml and metrics.yml, the only place any parameter is set
src/              ingestion, config loading, the mutation probe
dbt/              models, tests, macros
scripts/          vintage replay, report and dictionary generation, sample builder
reports/          measure dictionary, BI handoff, and generated/ for the numbers
tests/            Python unit tests over the vintage logic
```

Every number in this file, in the memo and in the dictionary is generated by
`scripts/generate_reports.py` querying the warehouse. None is typed by hand.

## Licence

MIT.
