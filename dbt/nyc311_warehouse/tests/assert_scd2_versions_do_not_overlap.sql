{{ config(severity='error') }}

-- No natural key may have two versions valid at the same instant.
--
-- If intervals overlapped, the fact join would match more than one version and
-- the fact table would gain rows, which is how an SCD2 bug usually shows up:
-- not as a wrong answer but as a row count that quietly grew.

with ordered as (

    select
        complaint_type,
        descriptor,
        version_number,
        valid_from_at,
        valid_to_at,
        lag(valid_to_at) over (
            partition by complaint_type, descriptor
            order by valid_from_at
        ) as previous_valid_to_at
    from {{ ref('dim_complaint_type') }}
    where not is_unknown_member

)

select *
from ordered
where previous_valid_to_at is not null
  and valid_from_at < previous_valid_to_at
