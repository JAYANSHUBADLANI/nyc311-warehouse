{{ config(materialized='table') }}

-- Grain: one row per service request. One request, one row, always.
--
-- Justifying the grain, since this is the decision everything else inherits.
-- A 311 request is the atomic unit the city actually manages: it is opened
-- once, worked once and closed once, and every operational question in the
-- memo (how long did it take, is it still open, did it meet target) is a
-- property of that single object. There is no lower grain available in this
-- source. The dataset carries no work log, no per-touch event and no assignment
-- history, only the request and a handful of timestamps on it, so a
-- transaction grain fact would be inventing events that were never published.
--
-- What this grain gives up: a request that is reassigned between agencies
-- shows only its final agency, and a reopened request is one row rather than
-- two spells. Both are stated in the measure dictionary rather than papered
-- over, because both change how the numbers should be read.
--
-- The complaint type join is deliberately not a join to the current version.
-- It resolves to whichever version was in force when the request was created,
-- which is the entire point of the dimension being Type 2.

with requests as (

    select * from {{ ref('int_requests_valid') }}

),

complaint_versions as (

    select * from {{ ref('dim_complaint_type') }}
    where not is_unknown_member

),

joined as (

    select
        r.request_id,

        r.created_at,
        r.closed_at,
        r.due_at,
        r.resolution_updated_at,
        r.ingested_at,
        r.source_updated_at,

        cast(r.created_at as date)          as created_date_key,
        cast(r.closed_at as date)           as closed_date_key,

        coalesce(r.agency_code, 'UNKNOWN')  as agency_key,

        {{ surrogate_key([
            "coalesce(r.borough, 'UNKNOWN')",
            "coalesce(r.community_board, 'UNKNOWN')",
            "coalesce(r.incident_zip, 'UNKNOWN')"
        ]) }}                               as geography_key,

        -- Type 2 resolution. The interval is half open, opened exclusive and
        -- closed inclusive, so exactly one version matches any created_at.
        coalesce(cv.complaint_type_key, 'UNKNOWN') as complaint_type_key,

        r.complaint_type,
        r.descriptor,
        r.status_raw,
        r.location_type,
        r.open_data_channel_type,
        r.latitude,
        r.longitude,

        r.dq_warn_coords_outside_nyc,
        r.dq_warn_missing_complaint_type,
        r.dq_warn_missing_agency,
        r.dq_warn_due_before_created

    from requests r
    left join complaint_versions cv
      on  cv.complaint_type = r.complaint_type
      and cv.descriptor     = coalesce(r.descriptor, '<<none>>')
      and r.created_at      >  cv.valid_from_at
      and r.created_at      <= cv.valid_to_at

),

measured as (

    select
        *,

        (closed_at is not null)                                   as is_closed,

        -- Duration is only defined for a request that has actually closed.
        -- Leaving it null rather than zero for an open request matters: an
        -- average over a column where open requests scored zero would be
        -- pulled toward zero by exactly the slow tickets that have not
        -- finished yet, which is the bias this project is about.
        case
            when closed_at is not null
            then {{ days_between('created_at', 'closed_at') }}
        end                                                       as days_to_close,

        -- Age is defined for every request: elapsed for open ones, final for
        -- closed ones. build_as_of comes from config, never current_date, so
        -- reruns are reproducible.
        case
            when closed_at is not null
            then {{ days_between('created_at', 'closed_at') }}
            else {{ days_between('created_at', "cast('" ~ var('build_as_of') ~ "' as timestamp)") }}
        end                                                       as age_days,

        -- Whether the request had reached the maturity horizon by build time.
        -- A request younger than the horizon has not had a full chance to
        -- close, so cohort measures exclude it rather than counting it as
        -- unresolved.
        {{ days_between('created_at', "cast('" ~ var('build_as_of') ~ "' as timestamp)") }}
            >= {{ var('maturity_window_days') }}                  as is_mature_at_build,

        -- On time against the configured target. Null for a request that is
        -- still open and still inside target, because whether it will meet
        -- target is genuinely not known yet. Recording that as a failure would
        -- overstate lateness, and as a success would understate it.
        case
            when closed_at is not null
            then {{ days_between('created_at', 'closed_at') }} <= {{ var('sla_target_days') }}
            when {{ days_between('created_at', "cast('" ~ var('build_as_of') ~ "' as timestamp)") }}
                 > {{ var('sla_target_days') }}
            then false
        end                                                       as is_within_target

    from joined

)

select
    request_id,

    created_date_key,
    closed_date_key,
    agency_key,
    complaint_type_key,
    geography_key,

    created_at,
    closed_at,
    due_at,
    resolution_updated_at,
    ingested_at,
    source_updated_at,

    complaint_type,
    descriptor,
    status_raw,
    location_type,
    open_data_channel_type,
    latitude,
    longitude,

    is_closed,
    days_to_close,
    age_days,
    is_mature_at_build,
    is_within_target,

    dq_warn_coords_outside_nyc,
    dq_warn_missing_complaint_type,
    dq_warn_missing_agency,
    dq_warn_due_before_created

from measured
