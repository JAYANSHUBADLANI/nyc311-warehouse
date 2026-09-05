# What the vintage replay cannot see, measured

The replay reconstructs each historical vintage from the timestamps in a single pull. That recovers restatement of the close date exactly, and it is blind to any edit that overwrites a value in place, because a single snapshot carries no record that the old value ever existed.

This probe bounds that blind spot rather than leaving it as an assertion. It recorded every field of 3,000 requests at 2026-08-28T17:52:36+00:00, refetched the same ids at 2026-09-05T13:09:22+00:00, and diffed them. The sample is drawn from the most recent complete month on purpose, because that is where restatement actually happens; an older sample would report a rate near zero that said more about the sample than about the source.

**Gap: 187.28 hours, 7.8 days. 84 of 3,000 requests changed, 2.8%.**

## Fields the replay reconstructs correctly

| Field | Changed | Share of sample |
| --- | --- | --- |
| closed_date | 79 | 2.63% |
| status | 79 | 2.63% |
| resolution_action_updated_date | 84 | 2.80% |

These are the closure restatements. The replay handles them by construction, and they are the same movement the append only versus merge comparison measures.

## Fields the replay is blind to

| Field | Changed | Share of sample |
| --- | --- | --- |
| complaint_type | 0 | 0.00% |
| descriptor | 0 | 0.00% |
| agency | 0 | 0.00% |
| created_date | 0 | 0.00% |

## What this establishes

Over 7.8 days, no request in the sample was reclassified: not one change of complaint type, descriptor or owning agency. Every mutation observed was a closure being recorded or revised, which is exactly the class the replay reconstructs.

That is a bound, not a proof of absence. With zero events in 3,000 observations the rule of three puts the 95% upper bound on the reclassification rate at roughly 0.10% per 7.8 day window. So in place reclassification is either absent or rare enough that it cannot materially move the vintage comparison, and the replay's blind spot is small rather than merely unmeasured.

A longer gap would tighten this further. The capture is on disk and `make probe-recheck` can be rerun against it at any time, so the bound improves by waiting rather than by writing anything.
