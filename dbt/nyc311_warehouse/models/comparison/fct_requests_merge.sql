{{
    config(
        materialized='incremental',
        unique_key='request_id',
        incremental_strategy='delete+insert',
        schema='comparison'
    )
}}

-- The same model done correctly, so the two can be compared.
--
-- Identical source, identical columns, identical vintage sequence. The only
-- difference from fct_requests_append_only is the incremental strategy: a key
-- already in the table is replaced by its newer version rather than skipped.
-- That single config line is the entire fix for restatement.
--
-- delete+insert rather than merge because it is the strategy dbt-duckdb
-- implements natively, and on a single unique key the two are equivalent:
-- delete the keys in this batch, insert the batch. The semantics that matter,
-- last writer wins per key, are the same.

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
