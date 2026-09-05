{{ config(severity='error') }}

-- Duration and age must never be negative. Negative duration would mean the
-- close preceded the open, which is quarantined, and negative age would mean
-- the request was created after the build instant, which would mean the ingest
-- window and the build instant disagree.

select
    request_id,
    created_at,
    closed_at,
    days_to_close,
    age_days
from {{ ref('fct_service_request') }}
where days_to_close < 0
   or age_days < 0
