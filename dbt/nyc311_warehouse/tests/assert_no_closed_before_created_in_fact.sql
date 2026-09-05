{{ config(severity='error') }}

-- A closure that precedes its own creation is impossible, and rows carrying one
-- are quarantined upstream. This asserts none survived into the fact table.
--
-- Error severity on purpose. The equivalent check on staging is a warning,
-- because the source genuinely contains these rows and that is a fact about the
-- data. Here it is an invariant, because the quarantine step is supposed to
-- have removed them, and if one appears the pipeline is broken rather than the
-- data being dirty.

select
    request_id,
    created_at,
    closed_at
from {{ ref('fct_service_request') }}
where closed_at is not null
  and closed_at < created_at
