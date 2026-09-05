{{ config(materialized='table') }}

-- One row per agency code seen in the window.
--
-- Why this is a dimension and not just a column on the fact: the agency code
-- carries a descriptive attribute the fact does not need repeated 3.9 million
-- times (the full agency name), the code is the natural join key for anything
-- the city publishes about agencies, and an "unknown agency" member is needed
-- so that facts with a missing agency still join rather than being lost to an
-- inner join. It is deliberately Type 1: agency names are corrected in place in
-- the source and there is no analytical question here that asks what an
-- agency's name used to be.
--
-- The name is picked as the most frequent non null agency_name for the code,
-- because the source occasionally carries several spellings for one agency.
-- Ties are broken alphabetically so the choice is deterministic.

with observed as (

    select
        agency_code,
        agency_name,
        count(*) as n
    from {{ ref('int_requests_valid') }}
    where agency_code is not null
    group by 1, 2

),

ranked as (

    select
        agency_code,
        agency_name,
        n,
        row_number() over (
            partition by agency_code
            order by n desc, agency_name asc
        ) as rn
    from observed

),

resolved as (

    select
        agency_code,
        agency_name,
        (select sum(o.n) from observed o where o.agency_code = r.agency_code) as request_count,
        (select count(*) from observed o where o.agency_code = r.agency_code) as distinct_names_seen
    from ranked r
    where rn = 1

)

select
    agency_code                                          as agency_key,
    agency_code,
    agency_name,
    request_count,
    distinct_names_seen,
    false                                                as is_unknown_member
from resolved

union all

-- Unknown member, so that a fact row with no agency still joins. Its key is a
-- literal rather than a null, because null keys do not join.
select
    'UNKNOWN'                                            as agency_key,
    null                                                 as agency_code,
    'Unknown or missing agency'                          as agency_name,
    (select count(*) from {{ ref('int_requests_valid') }} where agency_code is null) as request_count,
    0                                                    as distinct_names_seen,
    true                                                 as is_unknown_member
