# Cohort maturity: the naive series next to the corrected one

The naive mean is computed over closed requests only, which is what a pipeline publishes if nobody thinks about censoring. The corrected mean observes every cohort for the same fixed window and ignores closures after it, so cohorts are comparable regardless of age.

The unresolved column is the honest companion to the corrected mean: it is the share of the cohort the correction truncated. A fast corrected mean sitting next to a high unresolved share does not mean fast.

| Cohort | Requests | Age at build (days) | Mature | Closed so far | Naive mean days | Corrected mean days | Gap (days) | Gap % | Unresolved at 90d |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-09-01 | 302,622 | 332.0 | yes | 97.8% | 7.31 | 3.88 | -3.44 | -47.0% | 4.1% |
| 2025-10-01 | 336,576 | 301.0 | yes | 97.9% | 8.04 | 4.13 | -3.91 | -48.6% | 4.5% |
| 2025-11-01 | 304,807 | 271.0 | yes | 98.5% | 8.40 | 4.17 | -4.23 | -50.3% | 4.3% |
| 2025-12-01 | 332,064 | 240.0 | yes | 98.5% | 8.32 | 4.39 | -3.93 | -47.3% | 4.4% |
| 2026-01-01 | 348,468 | 209.0 | yes | 97.5% | 8.47 | 5.54 | -2.93 | -34.6% | 4.9% |
| 2026-02-01 | 334,654 | 181.0 | yes | 96.7% | 7.42 | 5.47 | -1.96 | -26.4% | 4.9% |
| 2026-03-01 | 342,360 | 150.0 | yes | 96.5% | 6.56 | 5.56 | -1.00 | -15.3% | 4.3% |
| 2026-04-01 | 302,153 | 120.0 | yes | 96.3% | 5.81 | 5.20 | -0.61 | -10.5% | 4.2% |
| 2026-05-01 | 331,935 | 89.0 | no | 95.7% | 4.90 | n/a | n/a | n/a | n/a |
| 2026-06-01 | 334,753 | 59.0 | no | 94.7% | 4.11 | n/a | n/a | n/a | n/a |
| 2026-07-01 | 342,934 | 28.0 | no | 90.7% | 3.41 | n/a | n/a | n/a | n/a |
| 2026-08-01 | 276,676 | -3.0 | no | 78.8% | 1.46 | n/a | n/a | n/a | n/a |
