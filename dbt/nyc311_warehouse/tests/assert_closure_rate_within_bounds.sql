{{ config(severity='error') }}

-- Every rate in the metrics mart must sit between zero and one.
--
-- A rate above one is the classic symptom of mixing a period basis numerator
-- with a cohort basis denominator, which is exactly the mistake the measure
-- dictionary rules out. This test is what stops it being reintroduced.

select
    cohort_month,
    agency_key,
    closure_rate,
    closure_rate_at_maturity,
    on_time_rate,
    unresolved_share_at_maturity
from {{ ref('mart_agency_month') }}
where closure_rate                 not between 0 and 1
   or (closure_rate_at_maturity     is not null and closure_rate_at_maturity     not between 0 and 1)
   or (on_time_rate                 is not null and on_time_rate                 not between 0 and 1)
   or (unresolved_share_at_maturity is not null and unresolved_share_at_maturity not between 0 and 1)
