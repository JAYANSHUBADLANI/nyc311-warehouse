{{ config(materialized='table') }}

-- The BI handoff: one wide, pre-aggregated table meant to be exported and
-- opened in a desktop BI tool with no database behind it.
--
-- This is the data half of a dashboard and nothing more. No dashboard was
-- built, and claiming otherwise would be the kind of thing that falls apart in
-- the first minute of being asked about it. What is here is the table a
-- dashboard would sit on, plus the documentation of what to put on it, in
-- reports/bi_handoff.md.
--
-- Joins are pre-resolved on purpose. A desktop BI tool given a star schema will
-- either make the analyst rebuild the relationships by hand or will silently
-- fan out a many to many join and double count. Resolving them here means the
-- grain is fixed and stated, and the tool is only asked to filter and sum.
--
-- Grain: cohort month, agency, complaint type, borough. One row per
-- combination that had at least one request. Because the grain is fixed, every
-- additive measure below sums correctly across any subset of the dimensions,
-- with the two exceptions called out in the column comments.

with base as (

    select
        m.cohort_month,
        m.agency_key,
        m.complaint_type_key,
        m.complaint_type,
        m.borough,
        m.is_cohort_mature,

        m.request_volume,
        m.closed_volume,
        m.backlog_open_count,
        m.on_time_denominator,

        m.closure_rate,
        m.closure_rate_at_maturity,
        m.mean_days_to_close,
        m.median_days_to_close,
        m.mean_days_to_close_matured,
        m.unresolved_share_at_maturity,
        m.on_time_rate

    from {{ ref('mart_agency_month') }} m

),

labelled as (

    select
        b.*,
        a.agency_name,
        d.owning_agency_code       as complaint_type_owning_agency,
        d.version_number           as complaint_type_version,
        d.is_current               as complaint_type_version_is_current,
        dd.year_month              as cohort_year_month,
        dd.calendar_year           as cohort_year,
        dd.calendar_quarter        as cohort_quarter
    from base b
    left join {{ ref('dim_agency') }} a
      on a.agency_key = b.agency_key
    left join {{ ref('dim_complaint_type') }} d
      on d.complaint_type_key = b.complaint_type_key
    left join {{ ref('dim_date') }} dd
      on dd.date_key = b.cohort_month

)

select
    -- dimensions, all pre-joined and human readable
    cohort_month,
    cohort_year_month,
    cohort_year,
    cohort_quarter,
    agency_key                                    as agency_code,
    agency_name,
    complaint_type,
    complaint_type_owning_agency,
    complaint_type_version,
    complaint_type_version_is_current,
    borough,
    is_cohort_mature,

    -- additive measures: safe to sum across any combination of dimensions
    request_volume,
    closed_volume,
    on_time_denominator,

    -- semi additive: a stock at the build instant. Sums across agencies and
    -- boroughs, does not sum across cohort months, because the same open
    -- request is counted in exactly one cohort but the total is a point in
    -- time figure rather than a flow.
    backlog_open_count,

    -- non additive: ratios and averages. Never sum or average these across
    -- rows. To aggregate, rebuild from the components, for example
    -- sum(closed_volume) / sum(request_volume) rather than avg(closure_rate).
    closure_rate,
    closure_rate_at_maturity,
    mean_days_to_close,
    median_days_to_close,
    mean_days_to_close_matured,
    unresolved_share_at_maturity,
    on_time_rate,

    -- weighted reaggregation helpers, so a BI tool can rebuild the averages
    -- correctly without needing the fact table. mean over any subset is
    -- sum(days_to_close_total) / sum(closed_volume).
    mean_days_to_close * closed_volume            as days_to_close_total,
    case
        when is_cohort_mature
        then mean_days_to_close_matured * (closure_rate_at_maturity * request_volume)
    end                                           as days_to_close_matured_total,
    case
        when is_cohort_mature
        then closure_rate_at_maturity * request_volume
    end                                           as closed_within_window_volume,
    on_time_rate * on_time_denominator            as on_time_numerator

from labelled
order by cohort_month, agency_code, complaint_type, borough
