{{ config(materialized='table') }}

-- The naive duration series and the corrected one, side by side, with the bias
-- between them quantified.
--
-- The problem this exists to show: "mean days to close by month" computed over
-- closed requests only will always show recent months as faster, whether or not
-- anything got faster. A request that will eventually take 200 days to close is
-- invisible in a cohort that is only 60 days old, because it has not closed and
-- so contributes to neither the numerator nor the denominator. The measure is
-- not noisy, it is biased, and the bias has a predictable sign.
--
-- Two corrections are offered rather than one, because they answer different
-- questions and disagree in a useful way:
--
--   fixed window   every cohort is observed for exactly maturity_window_days
--                  and closures after that are ignored. Comparable across
--                  months by construction. Truncates the tail, so it is
--                  reported next to the share it truncated.
--
--   restricted     the naive mean recomputed over only those cohorts that are
--                  fully mature. Does not correct the measure, it just refuses
--                  to plot the months where it is least trustworthy.
--
-- The gap between naive and fixed window, on the same mature cohorts, is the
-- bias estimate. It is reported per cohort rather than as a single headline,
-- because it grows as cohorts get younger and a single number would hide that.

with facts as (

    select
        cast(date_trunc('month', created_at) as date) as cohort_month,
        agency_key,
        request_id,
        is_closed,
        days_to_close
    from {{ ref('fct_service_request') }}

),

cohort_age as (

    select
        cohort_month,
        {{ days_between(
            "cast(cohort_month + interval 1 month - interval 1 second as timestamp)",
            "cast('" ~ var('build_as_of') ~ "' as timestamp)"
        ) }} as cohort_age_days_at_build
    from (select distinct cohort_month from facts)

),

joined as (

    select
        f.*,
        a.cohort_age_days_at_build,
        a.cohort_age_days_at_build >= {{ var('maturity_window_days') }} as is_cohort_mature,
        (f.is_closed and f.days_to_close <= {{ var('maturity_window_days') }}) as closed_within_window,
        case
            when f.is_closed and f.days_to_close <= {{ var('maturity_window_days') }}
            then f.days_to_close
        end as days_to_close_within_window
    from facts f
    join cohort_age a using (cohort_month)

),

by_cohort as (

    select
        cohort_month,
        cohort_age_days_at_build,
        is_cohort_mature,

        count(*)                                       as cohort_size,
        sum(case when is_closed then 1 else 0 end)     as closed_so_far,

        -- the biased series, exactly as a naive pipeline would publish it
        avg(days_to_close)                             as naive_mean_days_to_close,
        median(days_to_close)                          as naive_median_days_to_close,

        -- the corrected series, same observation window for every cohort
        case when is_cohort_mature then avg(days_to_close_within_window) end
                                                       as matured_mean_days_to_close,
        case when is_cohort_mature then median(days_to_close_within_window) end
                                                       as matured_median_days_to_close,

        -- how much mass the correction truncated
        case
            when is_cohort_mature
            then 1.0 - (cast(sum(case when closed_within_window then 1 else 0 end) as double)
                        / nullif(count(*), 0))
        end                                            as unresolved_share_at_maturity,

        cast(sum(case when is_closed then 1 else 0 end) as double)
            / nullif(count(*), 0)                      as closure_rate_so_far

    from joined
    group by 1, 2, 3

)

select
    cohort_month,
    cohort_age_days_at_build,
    is_cohort_mature,
    cohort_size,
    closed_so_far,
    closure_rate_so_far,

    naive_mean_days_to_close,
    naive_median_days_to_close,
    matured_mean_days_to_close,
    matured_median_days_to_close,
    unresolved_share_at_maturity,

    -- The bias: how much lower the naive figure reads than the corrected one
    -- for the same cohort. Positive means the naive series is flattering.
    case
        when is_cohort_mature
        then matured_mean_days_to_close - naive_mean_days_to_close
    end as naive_understatement_days,

    case
        when is_cohort_mature and naive_mean_days_to_close > 0
        then (matured_mean_days_to_close - naive_mean_days_to_close)
             / naive_mean_days_to_close
    end as naive_understatement_pct

from by_cohort
order by cohort_month
