{{
    config(
        materialized='incremental',
        incremental_strategy='append',
        schema='comparison'
    )
}}

-- The wrong way to do it, built properly so the error can be measured.
--
-- This is the pattern that shows up in most portfolio dbt projects: an
-- incremental model that inserts rows it has not seen before and never revisits
-- a row it has. On a source where records are only ever created it is correct
-- and cheap. On a source where records are restated after first load, which is
-- every real operational source, it freezes each record in whatever state it
-- happened to be in the first time the pipeline saw it.
--
-- For 311 that means a ticket first seen while open stays open in this table
-- for ever, no matter how long ago it actually closed. The closure is not lost
-- because it was hard to capture, it is lost because the model never asks.
--
-- The guard below is the load bearing line. It is what makes this append only
-- rather than merge, and removing it turns this model into a duplicate factory
-- rather than into a correct one.

select
    request_id,
    created_at,
    closed_at,
    status_at_vintage,
    is_closed_at_vintage,
    days_to_close_at_vintage,
    source_updated_at,
    agency_code,
    complaint_type,
    descriptor,
    borough,
    community_board,
    incident_zip,
    loaded_at_vintage
from {{ ref('int_vintage_source') }}

{% if is_incremental() %}
-- keys already present are skipped entirely, restatement and all
where request_id not in (select request_id from {{ this }})
{% endif %}
