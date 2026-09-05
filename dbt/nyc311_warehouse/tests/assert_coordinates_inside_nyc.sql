{{ config(severity='error') }}

-- Any coordinate surviving into the fact table must be inside the New York
-- City bounding box. Out of range points are nulled in staging rather than
-- causing the row to be dropped, so a point outside the box here means the
-- nulling logic failed rather than that the source was wrong.

select
    request_id,
    latitude,
    longitude
from {{ ref('fct_service_request') }}
where latitude is not null
  and longitude is not null
  and not (
        latitude  between 40.4 and 41.0
    and longitude between -74.3 and -73.7
  )
