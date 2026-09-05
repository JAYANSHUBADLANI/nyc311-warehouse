# How fast does the city actually close 311 requests?

**To:** operations leadership
**From:** analytics engineering
**Window:** service requests created 1 September 2025 to 28 August 2026, 3,890,002 requests across 17 agencies
**Date of analysis:** 28 August 2026

## The short version

Resolution times have not improved over the past year. They have got slower, by
about a day and a third on a like for like basis. Any report showing recent
months closing faster is measuring cohorts that have not finished closing, and
the effect is large enough to reverse the direction of the trend.

Separately, and more urgently: a pipeline that appends new requests without
revisiting old ones understates the mean time to close by 76%. If any reporting
in the organisation is built that way, it is reporting 1.5 days where the real
figure is 6.3.

## What was asked

How fast does each agency close the request types it owns, how has that changed,
and how much of any apparent improvement is real.

## What the numbers say

**1. The apparent improvement is not real.**

Averaging the duration of requests that have closed, by the month the request
was created, gives this:

| Cohort month | Mean days to close, as usually reported |
| --- | --- |
| September 2025 | 7.31 |
| December 2025 | 8.32 |
| March 2026 | 6.56 |
| July 2026 | 3.41 |
| August 2026 | 1.46 |

Read straight, that is an 80% improvement in a year. It is an artefact of when
the measurement was taken. The August cohort was 27 days old when this was
built, and its month had not finished, so the only requests in it that had
closed were the quick ones. The slow
ones were still open, and an open request contributes no duration at all, so it
does not pull the average up. Every cohort is measured at a different age, and
younger cohorts are structurally flattered.

Measuring every cohort over the same fixed 90 day window removes that:

| Cohort month | Like for like mean days to close |
| --- | --- |
| September 2025 | 3.88 |
| December 2025 | 4.39 |
| March 2026 | 5.56 |
| April 2026 | 5.20 |

That is a deterioration of roughly 1.3 days, about a third slower, over the
period where a like for like comparison is possible. The last four months of the
window cannot be compared yet, and will not be until they are 90 days old.

**2. Agency performance varies by two orders of magnitude, so citywide averages
are not useful.**

| Agency | Requests | Closure rate | Like for like mean days |
| --- | --- | --- | --- |
| NYPD | 1,709,166 | 99.9% | 0.10 |
| HPD | 882,962 | 93.2% | 9.72 |
| DSNY | 355,413 | 98.0% | 3.17 |
| DOT | 272,902 | 92.9% | 6.30 |
| DEP | 214,152 | 96.7% | 3.92 |
| DPR | 131,621 | 67.1% | 12.49 |
| DOHMH | 80,896 | 86.4% | 22.73 |
| TLC | 38,440 | 43.9% | 15.25 |

NYPD is 44% of all requests and closes them in a tenth of a day, which reflects
a fundamentally different process to HPD taking nearly ten days on a housing
complaint. A single citywide average is mostly a measure of how many noise
complaints were filed. It should not be reported.

The two to look at are **DPR at 67.1% closed and DOHMH at 22.73 days**. DPR has
43,306 requests still open from this window. TLC is worse in rate terms, 43.9%
with 21,564 open, on a much smaller base.

**3. Nearly 190,000 requests are still open from this window.**

188,861 requests created in the last twelve months had not closed at the time of
measurement. 60,150 of those are HPD and 43,306 are DPR, so two agencies hold
55% of the open backlog.

## What this assumes

**A request that was reopened is counted once.** The source reuses the same
identifier and overwrites the close date when a request is reopened, so there is
no way to see that it happened. A request closed, reopened and closed again
looks identical to one that simply took that long. This inflates the measured
duration for reopened requests and cannot be corrected from this data.

**Requests are attributed to the month they were created**, not the month work
happened. Both are reasonable; they answer different questions. Mixing them
produces ratios that can exceed 100% and mean nothing.

**On time performance uses a single 30 day target for every agency and request
type.** The real targets differ by both. Treat the on time measure as
indicative only. This is the weakest number in the pack.

**The 90 day maturity window is a judgement call.** It was chosen because it
leaves eight of twelve cohorts comparable while capturing most closures.
Changing it changes every like for like figure above, so the series was
recomputed at 30, 60, 120 and 180 days as well. The direction is the same at all
of them: slower, not faster. The size of the deterioration is not, ranging from
a quarter of a day to over two, so treat the direction as settled and the
magnitude as approximate.

## What would change the answer

**A per agency and request type SLA table.** This is the single highest value
addition. It would turn on time performance from indicative into something an
operations owner could be held to, and it is a data collection problem rather
than a modelling one.

**Waiting.** Four of the twelve cohorts are not yet mature. When they reach 90
days the trend can be extended to the present, and the deterioration either
continues or does not. Nothing else needs to be built to answer that.

**Understanding DOB and EDC.** Both were open questions when this was drafted
and both are now settled. DOB's 100% is a definitional artefact: it records a
close timestamp on 17,568 requests its own status field still calls Open or
Assigned, and scored on that status it closes 84.9%, not 100%. EDC's 1.9% is
real in the sense that the closures genuinely are not recorded, so it is either
a true backlog or an agency that closes work outside this system, and that
distinction needs someone at EDC rather than more analysis. Both stay out of
cross agency comparison. Citywide the effect is 0.57% of requests, so nothing
else in this memo moves.

## The technical finding, stated plainly for the record

The warehouse was built twice: once appending only new requests, once updating
requests whose status had changed. Fed identical data, the appending version
reported a mean resolution time of 1.50 days against the correct 6.33, and a
closure rate of 82.7% against the correct 95.1%. It was unaware of 483,003
closures, 13% of the total.

The reason it matters operationally rather than just technically is the shape of
the error over time. It was exactly zero at the first month, because nothing had
been restated yet, and grew every month after without settling. A pipeline built
that way looks correct on the day it ships and degrades quietly and
indefinitely. It is worth confirming that no existing reporting is built this
way.
