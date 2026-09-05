# Does the corrected trend survive a different maturity window?

The 90 day maturity window is a choice, not a derivation. It was picked because it leaves most cohorts comparable while capturing the bulk of closures, and every corrected number in this project moves with it.

So the honest test is not what the corrected series says at 90 days. It is whether the direction it reports, that resolution time got slower rather than faster, is a property of the data or a property of the window. Each row below recomputes the whole corrected series at a different window and compares its first mature cohort against its last.

| Window (days) | Mature cohorts | First | Last | Corrected mean, first | Corrected mean, last | Worst cohort truncated | Direction |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 30 | 10 | 2025-09-01 | 2026-06-01 | 2.22 | 2.50 | 10.5% | slower by 0.28 days |
| 60 | 9 | 2025-09-01 | 2026-05-01 | 3.37 | 3.63 | 7.1% | slower by 0.27 days |
| 90 | 8 | 2025-09-01 | 2026-04-01 | 3.88 | 5.20 | 4.9% | slower by 1.32 days |
| 120 | 7 | 2025-09-01 | 2026-03-01 | 4.28 | 6.18 | 3.9% | slower by 1.90 days |
| 180 | 6 | 2025-09-01 | 2026-02-01 | 5.17 | 7.31 | 3.3% | slower by 2.14 days |

A shorter window admits more cohorts and truncates more of each one. A longer window truncates less but leaves fewer cohorts comparable, and past a point there are too few left to read a trend from at all. The column that matters is the last one: if the direction flips across these rows then the finding belongs to the window rather than to the city.

It does not flip. Every window tested reports the same direction, so the conclusion that resolution time got slower is a property of the data and not of the 90 day choice.

The magnitude is a different matter and it grows with the window, from about a quarter of a day at 30 to over two days at 180. Two things drive that and they cannot be separated here. A short window truncates away the slow tail, which is exactly where the deterioration lives, so it understates the effect. But each row also ends on a different cohort, because a longer window disqualifies the recent months, so the rows are not measuring the same span of time. Read the direction as robust and the size as window dependent.
