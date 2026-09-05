{{ config(materialized='table') }}

-- The metrics mart. Every measure in config/metrics.yml is implemented here
-- exactly once, and metrics_definitions_are_implemented asserts that the two
-- lists match, so a metric cannot be documented without being built or built
-- without being documented.
--
-- Grain: created month, agency, complaint type, borough. Cohort basis
-- throughout, meaning a request belongs to the month it was created in and
-- stays there no matter when it closes. The mixed form, closures this month
-- over creations this month, is deliberately not offered anywhere in this
-- project because the ratio it produces is not interpretable.

with facts as (

    -- borough comes from the geography dimension rather than being carried on
    -- the fact, which is the point of having the dimension. The fact stays
    -- narrow and the slicing attribute is stored once.
    select
        f.*,
        g.borough                                       as borough_key,
        cast(date_trunc('month', f.created_at) as date) as cohort_month
    from {{ ref('fct_service_request') }} f
    join {{ ref('dim_geography') }} g
      on g.geography_key = f.geography_key

),

cohort_maturity as (

    -- A cohort is mature only if its whole month is older than the maturity
    -- window at build time, so every request in it had the full window
    -- available. Testing the cohort rather than the individual request is what
    -- keeps the denominator stable: if maturity were tested per request, a
    -- partially mature month would silently drop its youngest requests and the
    -- rate would be computed over a shifting base.
    select
        cohort_month,
        (
            {{ days_between(
                "cast(cohort_month + interval 1 month - interval 1 second as timestamp)",
                "cast('" ~ var('build_as_of') ~ "' as timestamp)"
            ) }} >= {{ var('maturity_window_days') }}
        ) as is_cohort_mature
    from (select distinct cohort_month from facts)

),

enriched as (

    select
        f.*,
        m.is_cohort_mature,

        -- closed inside the observation window, which is the maturity
        -- corrected view of the same event
        (f.is_closed and f.days_to_close <= {{ var('maturity_window_days') }}) as closed_within_window,

        case
            when f.is_closed and f.days_to_close <= {{ var('maturity_window_days') }}
            then f.days_to_close
        end as days_to_close_within_window

    from facts f
    join cohort_maturity m using (cohort_month)

)

select
    cohort_month,
    agency_key,
    complaint_type_key,
    complaint_type,
    borough_key as borough,
    is_cohort_mature,

    -- volume
    count(*)                                                     as request_volume,
    sum(case when is_closed then 1 else 0 end)                   as closed_volume,

    -- closure, naive and corrected
    cast(sum(case when is_closed then 1 else 0 end) as double)
        / nullif(count(*), 0)                                    as closure_rate,

    case
        when is_cohort_mature
        then cast(sum(case when closed_within_window then 1 else 0 end) as double)
             / nullif(count(*), 0)
    end                                                          as closure_rate_at_maturity,

    -- duration, naive and corrected
    avg(days_to_close)                                           as mean_days_to_close,
    median(days_to_close)                                        as median_days_to_close,

    case
        when is_cohort_mature then avg(days_to_close_within_window)
    end                                                          as mean_days_to_close_matured,

    case
        when is_cohort_mature
        then 1.0 - (cast(sum(case when closed_within_window then 1 else 0 end) as double)
                    / nullif(count(*), 0))
    end                                                          as unresolved_share_at_maturity,

    -- stock
    sum(case when not is_closed then 1 else 0 end)               as backlog_open_count,

    -- target performance, denominator is requests with a known outcome only
    cast(sum(case when is_within_target then 1 else 0 end) as double)
        / nullif(sum(case when is_within_target is not null then 1 else 0 end), 0)
                                                                 as on_time_rate,
    sum(case when is_within_target is not null then 1 else 0 end) as on_time_denominator

from enriched
group by 1, 2, 3, 4, 5, 6
