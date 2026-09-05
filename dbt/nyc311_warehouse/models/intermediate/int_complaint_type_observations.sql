{{ config(materialized='table') }}

-- What the complaint type vocabulary looked like in each vintage period.
--
-- "Active in a period" means the pair appeared on at least one request created
-- during that period, not that it has ever existed. That distinction is the
-- reason this dimension can be Type 2 at all. A cumulative definition, "every
-- pair seen so far", only ever grows, so nothing retires and no version ever
-- closes. Scoping activity to the period lets a pair appear, fall out of use,
-- and come back, which is what the real vocabulary does.
--
-- The tracked attribute is the owning agency, taken as the agency that filed
-- the most requests of that pair in the period. NYC reassigns categories
-- between agencies, so this genuinely changes and is what the Type 2 history
-- records. Ties are broken alphabetically to keep the choice deterministic.

with vintages as (

    select
        vintage_date,
        vintage_cutoff_at,
        vintage_seq,
        lag(vintage_cutoff_at) over (order by vintage_seq) as previous_cutoff_at
    from {{ ref('int_vintage_dates') }}

),

periods as (

    select
        vintage_date,
        vintage_seq,
        vintage_cutoff_at,
        -- the first vintage opens at the start of the ingest window
        coalesce(
            previous_cutoff_at,
            cast('{{ var("window_start") }}' as timestamp) - interval 1 second
        ) as period_start_at
    from vintages

),

requests as (

    select
        request_id,
        created_at,
        complaint_type,
        descriptor,
        coalesce(agency_code, 'UNKNOWN') as agency_code
    from {{ ref('int_requests_valid') }}
    where complaint_type is not null

),

observed as (

    select
        p.vintage_date,
        p.vintage_seq,
        r.complaint_type,
        coalesce(r.descriptor, '<<none>>') as descriptor,
        r.agency_code,
        count(*)                          as request_count
    from periods p
    join requests r
      on r.created_at >  p.period_start_at
     and r.created_at <= p.vintage_cutoff_at
    group by 1, 2, 3, 4, 5

),

ranked as (

    select
        vintage_date,
        vintage_seq,
        complaint_type,
        descriptor,
        agency_code,
        request_count,
        sum(request_count) over (
            partition by vintage_date, complaint_type, descriptor
        ) as period_request_count,
        row_number() over (
            partition by vintage_date, complaint_type, descriptor
            order by request_count desc, agency_code asc
        ) as agency_rank,
        count(*) over (
            partition by vintage_date, complaint_type, descriptor
        ) as distinct_agencies_in_period
    from observed

)

select
    vintage_date,
    vintage_seq,
    complaint_type,
    descriptor,
    agency_code            as owning_agency_code,
    period_request_count,
    distinct_agencies_in_period
from ranked
where agency_rank = 1
