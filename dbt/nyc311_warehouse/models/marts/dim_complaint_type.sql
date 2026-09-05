{{ config(materialized='table') }}

-- Slowly changing dimension, Type 2, over the (complaint_type, descriptor) pair.
--
-- Why this pair and not something tidier: the 311 category vocabulary is
-- demonstrably unstable. Checked against the live API, 2020 carried 199
-- distinct complaint types, 2023 carried 216 and 2025 carried 193. Categories
-- are added, retired and reassigned between agencies. A Type 1 dimension would
-- overwrite that history and silently reclassify the past.
--
-- A new version opens on any of three events:
--   1. the pair is seen for the first time
--   2. the pair reappears after at least one period of no activity
--   3. the owning agency changes
--
-- Case 2 is the one most implementations get wrong. A pair that lapses and
-- returns must produce two disjoint intervals with a hole between them, not one
-- long interval that quietly asserts the category was in use throughout.
--
-- Validity is expressed as a half open interval, [valid_from_at, valid_to_at),
-- so that a fact created at the exact boundary instant matches exactly one
-- version. Closed intervals on both ends would double match at the seam.

with observations as (

    select * from {{ ref('int_complaint_type_observations') }}

),

periods as (

    select
        v.vintage_seq,
        v.vintage_date,
        v.vintage_cutoff_at,
        coalesce(
            lag(v.vintage_cutoff_at) over (order by v.vintage_seq),
            cast('{{ var("window_start") }}' as timestamp) - interval 1 second
        ) as period_start_at
    from {{ ref('int_vintage_dates') }} v

),

with_period_bounds as (

    select
        o.*,
        p.period_start_at,
        p.vintage_cutoff_at
    from observations o
    join periods p using (vintage_seq)

),

change_detection as (

    select
        *,
        lag(vintage_seq) over w          as previous_vintage_seq,
        lag(owning_agency_code) over w   as previous_owning_agency_code
    from with_period_bounds
    window w as (
        partition by complaint_type, descriptor
        order by vintage_seq
    )

),

versioned as (

    select
        *,
        sum(
            case
                -- first ever appearance of the pair
                when previous_vintage_seq is null then 1
                -- reappearance after a gap in activity
                when vintage_seq <> previous_vintage_seq + 1 then 1
                -- tracked attribute changed
                when owning_agency_code is distinct from previous_owning_agency_code then 1
                else 0
            end
        ) over (
            partition by complaint_type, descriptor
            order by vintage_seq
            rows between unbounded preceding and current row
        ) as version_number
    from change_detection

),

collapsed as (

    select
        complaint_type,
        descriptor,
        version_number,
        min(owning_agency_code)     as owning_agency_code,
        min(vintage_seq)            as first_vintage_seq,
        max(vintage_seq)            as last_vintage_seq,
        min(vintage_date)           as valid_from_vintage_date,
        max(vintage_date)           as valid_to_vintage_date,
        -- the version becomes valid at the start of the first period it covers
        min(period_start_at)        as valid_from_at,
        -- and stops being valid at the end of the last period it covers
        max(vintage_cutoff_at)      as valid_to_at_inclusive,
        sum(period_request_count)   as request_count_in_version,
        max(distinct_agencies_in_period) as max_distinct_agencies_in_a_period
    from versioned
    group by 1, 2, 3

),

final_vintage as (

    select max(vintage_seq) as final_seq from periods

),

shaped as (

    select
        {{ surrogate_key(['complaint_type', 'descriptor', 'version_number']) }} as complaint_type_key,

        complaint_type,
        descriptor,
        version_number,
        owning_agency_code,

        valid_from_vintage_date,
        valid_to_vintage_date,

        -- half open interval. valid_from_at is exclusive on the low side
        -- because period_start_at is the previous cutoff instant, so the
        -- comparison downstream is created_at > valid_from_at.
        valid_from_at,
        valid_to_at_inclusive,

        -- a version still active in the final vintage is the current one and
        -- is left open ended, so a fact created after the last replayed vintage
        -- still finds a match
        case
            when last_vintage_seq = (select final_seq from final_vintage)
            then cast('9999-12-31 23:59:59' as timestamp)
            else valid_to_at_inclusive
        end as valid_to_at,

        last_vintage_seq = (select final_seq from final_vintage) as is_current,

        (last_vintage_seq - first_vintage_seq + 1)              as periods_covered,
        request_count_in_version,
        max_distinct_agencies_in_a_period,
        false                                                   as is_unknown_member

    from collapsed

)

select * from shaped

union all

-- Unknown member for requests with no complaint type. Keyed with a literal so
-- the fact join stays an inner join and no row is lost to a null key.
select
    'UNKNOWN'                                          as complaint_type_key,
    null                                               as complaint_type,
    null                                               as descriptor,
    0                                                  as version_number,
    'UNKNOWN'                                          as owning_agency_code,
    cast('{{ var("window_start") }}' as date)          as valid_from_vintage_date,
    cast('9999-12-31' as date)                         as valid_to_vintage_date,
    cast('1900-01-01' as timestamp)                    as valid_from_at,
    cast('9999-12-31 23:59:59' as timestamp)           as valid_to_at_inclusive,
    cast('9999-12-31 23:59:59' as timestamp)           as valid_to_at,
    true                                               as is_current,
    0                                                  as periods_covered,
    (select count(*) from {{ ref('int_requests_valid') }} where complaint_type is null) as request_count_in_version,
    0                                                  as max_distinct_agencies_in_a_period,
    true                                               as is_unknown_member
