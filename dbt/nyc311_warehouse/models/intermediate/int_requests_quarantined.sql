{{ config(materialized='table') }}

-- Every request excluded from the fact table, with the reason it was excluded.
--
-- This model exists so that exclusion is a queryable fact rather than a
-- side effect of a WHERE clause. A row that fails more than one rule is
-- reported under the first reason in a fixed order, so the reason counts
-- partition the quarantine set exactly and can be summed without double
-- counting.

select
    request_id,
    created_at,
    closed_at,
    agency_code,
    complaint_type,
    status_raw,
    ingested_at,

    case
        when dq_fatal_missing_request_id     then 'missing_request_id'
        when dq_fatal_missing_created_at     then 'unparseable_or_missing_created_date'
        when dq_fatal_closed_before_created  then 'closed_before_created'
    end as exclusion_reason,

    dq_fatal_missing_request_id,
    dq_fatal_missing_created_at,
    dq_fatal_closed_before_created

from {{ ref('stg_service_requests') }}
where is_quarantined
