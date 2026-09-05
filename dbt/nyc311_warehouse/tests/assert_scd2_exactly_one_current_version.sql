{{ config(severity='error') }}

-- A natural key that is still in use must have exactly one open version, and a
-- retired one must have none. Two current versions means a change was detected
-- but the old version was never closed.

select
    complaint_type,
    descriptor,
    count(*) as current_versions
from {{ ref('dim_complaint_type') }}
where is_current
  and not is_unknown_member
group by 1, 2
having count(*) > 1
