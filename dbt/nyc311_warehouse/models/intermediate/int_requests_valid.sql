{{ config(materialized='table') }}

-- The set of requests that are fit to sit in the fact table.
--
-- Exclusion is only ever for a fatal flag, meaning the row cannot be placed at
-- the fact grain at all: no identifier, no created timestamp, or a close that
-- precedes its own open. Everything else stays, with the offending attribute
-- nulled rather than the row removed. Dropping a whole request because its
-- latitude was wrong would silently bias every count in the warehouse.
--
-- int_requests_quarantined holds the complement, and dq_exclusion_ledger
-- proves the two add back up to the landed row count.

select
    request_id,
    created_at,
    closed_at,
    due_at,
    resolution_updated_at,
    ingested_at,
    source_updated_at,

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
    latitude,
    longitude,

    dq_warn_coords_outside_nyc,
    dq_warn_missing_complaint_type,
    dq_warn_missing_agency,
    dq_warn_due_before_created

from {{ ref('stg_service_requests') }}
where not is_quarantined
