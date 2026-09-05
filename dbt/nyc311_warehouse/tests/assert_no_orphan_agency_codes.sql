{{ config(severity='error') }}

-- Every agency key on the fact must exist in the dimension.
--
-- This duplicates the relationships test on purpose and is kept because it
-- reads as the business rule rather than as a schema constraint, and because
-- it reports the offending codes rather than just a count, which is what you
-- want at three in the morning.

select
    f.agency_key,
    count(*) as orphan_rows
from {{ ref('fct_service_request') }} f
left join {{ ref('dim_agency') }} a
  on a.agency_key = f.agency_key
where a.agency_key is null
group by 1
