# Append only versus merge, by vintage

Both tables were built by dbt's own incremental machinery, fed byte for byte the same source rows at the same instants. The only difference between them is the incremental strategy.

That append only misses restatement is true by construction and is not presented as a discovery. The measured quantities below, how large the error is and how it behaves as vintages accumulate, are the finding.

| Vintage | Rows append | Rows merge | Closed append | Closed merge | Closures missed | Missed % | Closure rate append | Closure rate merge | Rate error | Mean days append | Mean days merge | Days error | Days error % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-09-30 | 302,622 | 302,622 | 258,454 | 258,454 | 0 | 0.00% | 0.8540 | 0.8540 | 0.0000 | 1.382 | 1.382 | 0.000 | 0.0% |
| 2025-10-31 | 639,198 | 639,198 | 544,566 | 570,524 | 25,958 | 4.55% | 0.8520 | 0.8926 | -0.0406 | 1.360 | 2.026 | -0.666 | -32.9% |
| 2025-11-30 | 944,005 | 944,005 | 804,729 | 862,377 | 57,648 | 6.68% | 0.8525 | 0.9135 | -0.0611 | 1.369 | 2.595 | -1.226 | -47.2% |
| 2025-12-31 | 1,276,069 | 1,276,069 | 1,091,271 | 1,181,390 | 90,119 | 7.63% | 0.8552 | 0.9258 | -0.0706 | 1.395 | 3.026 | -1.631 | -53.9% |
| 2026-01-31 | 1,624,537 | 1,624,537 | 1,358,119 | 1,480,821 | 122,702 | 8.29% | 0.8360 | 0.9115 | -0.0755 | 1.426 | 3.484 | -2.058 | -59.1% |
| 2026-02-28 | 1,959,191 | 1,959,191 | 1,631,258 | 1,815,906 | 184,648 | 10.17% | 0.8326 | 0.9269 | -0.0942 | 1.452 | 3.896 | -2.445 | -62.7% |
| 2026-03-31 | 2,301,551 | 2,301,551 | 1,913,034 | 2,150,246 | 237,212 | 11.03% | 0.8312 | 0.9343 | -0.1031 | 1.467 | 4.503 | -3.037 | -67.4% |
| 2026-04-30 | 2,603,704 | 2,603,704 | 2,163,767 | 2,458,491 | 294,724 | 11.99% | 0.8310 | 0.9442 | -0.1132 | 1.476 | 5.322 | -3.846 | -72.3% |
| 2026-05-31 | 2,935,639 | 2,935,639 | 2,438,815 | 2,784,810 | 345,995 | 12.42% | 0.8308 | 0.9486 | -0.1179 | 1.473 | 5.793 | -4.321 | -74.6% |
| 2026-06-30 | 3,270,392 | 3,270,392 | 2,719,398 | 3,117,326 | 397,928 | 12.77% | 0.8315 | 0.9532 | -0.1217 | 1.482 | 6.110 | -4.627 | -75.7% |
| 2026-07-31 | 3,613,326 | 3,613,326 | 3,000,225 | 3,443,117 | 442,892 | 12.86% | 0.8303 | 0.9529 | -0.1226 | 1.503 | 6.268 | -4.764 | -76.0% |
| 2026-08-28 | 3,890,002 | 3,890,002 | 3,218,137 | 3,701,140 | 483,003 | 13.05% | 0.8273 | 0.9514 | -0.1242 | 1.500 | 6.332 | -4.831 | -76.3% |

At the final vintage (2026-08-28) the append only table was unaware of 483,003 closures that a correctly merged table held, which is 13.05% of all the closures known at that point. It would have published a closure rate of 0.8273 against the correct 0.9514, and a mean resolution time of 1.50 days against the correct 6.33 days, understating it by 76.3%.

The worst vintage was 2026-08-28, where 13.05% of known closures were missing from the append only table.
