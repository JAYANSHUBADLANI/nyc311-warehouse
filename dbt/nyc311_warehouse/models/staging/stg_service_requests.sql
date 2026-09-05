{{ config(materialized='view') }}

-- Types and cleans the landing rows. Drops nothing.
--
-- Two jobs only: resolve the append log down to one row per request, and
-- attach data quality flags. Exclusion happens one layer up, in
-- int_requests_valid and int_requests_quarantined, so that every row this
-- model emits is accounted for in the ledger. If a row were dropped here it
-- would never appear in the reconciliation and the counts would not tie.

with landing as (

    select
        unique_key,
        created_date,
        closed_date,
        agency,
        agency_name,
        complaint_type,
        descriptor,
        location_type,
        incident_zip,
        incident_address,
        street_name,
        address_type,
        city,
        status,
        due_date,
        resolution_action_updated_date,
        community_board,
        borough,
        open_data_channel_type,
        latitude,
        longitude,
        _ingested_at,
        -- The landing table is an append log keyed on
        -- (unique_key, _ingested_at). Current state is the most recent
        -- ingestion of each key. Ties broken on closed_date so the ordering is
        -- total and two runs cannot disagree.
        row_number() over (
            partition by unique_key
            order by _ingested_at desc, closed_date desc nulls last
        ) as _ingestion_recency
    from {{ source('raw', 'service_requests_landing') }}

),

latest as (

    select * from landing where _ingestion_recency = 1

),

typed as (

    select
        trim(unique_key)                                     as request_id,
        try_cast(created_date as timestamp)                  as created_at,
        try_cast(closed_date as timestamp)                   as closed_at,
        try_cast(due_date as timestamp)                      as due_at,
        try_cast(resolution_action_updated_date as timestamp) as resolution_updated_at,
        try_cast(_ingested_at as timestamp)                  as ingested_at,

        nullif(trim(upper(agency)), '')                      as agency_code,
        nullif(trim(agency_name), '')                        as agency_name,
        nullif(trim(complaint_type), '')                     as complaint_type,
        nullif(trim(descriptor), '')                         as descriptor,
        nullif(trim(location_type), '')                      as location_type,
        nullif(trim(status), '')                             as status_raw,
        nullif(trim(upper(borough)), '')                     as borough,
        nullif(trim(community_board), '')                    as community_board,
        nullif(trim(incident_zip), '')                       as incident_zip,
        nullif(trim(incident_address), '')                   as incident_address,
        nullif(trim(street_name), '')                        as street_name,
        nullif(trim(address_type), '')                       as address_type,
        nullif(trim(city), '')                               as city,
        nullif(trim(open_data_channel_type), '')             as open_data_channel_type,

        try_cast(latitude as double)                         as latitude_raw,
        try_cast(longitude as double)                        as longitude_raw

    from latest

),

flagged as (

    select
        *,

        -- Quality flags. Naming is deliberate: dq_fatal_* means the row cannot
        -- sit in the fact table at all, dq_warn_* means the row is usable but
        -- one attribute is not. Only fatal flags cause quarantine.

        (request_id is null or request_id = '')              as dq_fatal_missing_request_id,
        (created_at is null)                                 as dq_fatal_missing_created_at,
        (closed_at is not null and closed_at < created_at)   as dq_fatal_closed_before_created,

        -- NYC sits inside roughly 40.4 to 41.0 N and -74.3 to -73.7 W. A
        -- coordinate outside that box is real in the source, it is just not in
        -- New York, so the point is nulled and the row is kept.
        (
            latitude_raw is not null
            and longitude_raw is not null
            and not (
                latitude_raw between 40.4 and 41.0
                and longitude_raw between -74.3 and -73.7
            )
        )                                                    as dq_warn_coords_outside_nyc,

        (complaint_type is null)                             as dq_warn_missing_complaint_type,
        (agency_code is null)                                as dq_warn_missing_agency,

        -- A due date is only meaningful if it is after the request opened.
        (due_at is not null and due_at < created_at)         as dq_warn_due_before_created

    from typed

)

select
    request_id,
    created_at,
    closed_at,
    due_at,
    resolution_updated_at,
    ingested_at,

    agency_code,
    agency_name,
    complaint_type,
    descriptor,
    location_type,
    status_raw,
    borough,
    community_board,
    incident_zip,
    incident_address,
    street_name,
    address_type,
    city,
    open_data_channel_type,

    -- coordinates are nulled when they fall outside the city, rather than the
    -- row being dropped for it
    case when dq_warn_coords_outside_nyc then null else latitude_raw end   as latitude,
    case when dq_warn_coords_outside_nyc then null else longitude_raw end  as longitude,

    -- The update timestamp an incremental model would key on. 311 has no single
    -- "last modified" column, so this is the best available proxy: the latest
    -- of the timestamps the source does maintain.
    greatest(
        created_at,
        coalesce(resolution_updated_at, created_at),
        coalesce(closed_at, created_at)
    )                                                                       as source_updated_at,

    dq_fatal_missing_request_id,
    dq_fatal_missing_created_at,
    dq_fatal_closed_before_created,
    dq_warn_coords_outside_nyc,
    dq_warn_missing_complaint_type,
    dq_warn_missing_agency,
    dq_warn_due_before_created,

    (
        dq_fatal_missing_request_id
        or dq_fatal_missing_created_at
        or dq_fatal_closed_before_created
    )                                                                       as is_quarantined

from flagged
