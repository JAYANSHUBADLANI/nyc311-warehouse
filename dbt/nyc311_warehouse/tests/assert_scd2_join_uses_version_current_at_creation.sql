{{ config(severity='error') }}

-- The test that proves the Type 2 dimension is actually being used as one.
--
-- It fails if any fact row is attached to a version of its complaint type
-- whose validity interval does not contain the moment the request was created.
-- The failure mode it is built to catch is the common one: joining on the
-- natural key alone and silently picking up the current version, which
-- reclassifies history to whatever the category means today.
--
-- Written to catch that specific bug rather than to restate the join. If
-- fct_service_request were changed to join on is_current, or to drop the
-- interval predicate, every fact row created before the latest version opened
-- would land here.

select
    f.request_id,
    f.created_at,
    f.complaint_type,
    d.complaint_type_key,
    d.version_number,
    d.valid_from_at,
    d.valid_to_at
from {{ ref('fct_service_request') }} f
join {{ ref('dim_complaint_type') }} d
  on d.complaint_type_key = f.complaint_type_key
where not d.is_unknown_member
  and not (
        f.created_at >  d.valid_from_at
    and f.created_at <= d.valid_to_at
  )
