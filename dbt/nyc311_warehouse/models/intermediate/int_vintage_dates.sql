{{ config(materialized='table') }}

-- The sequence of cutoff instants that get replayed through the pipeline.
--
-- A vintage is "what the warehouse would have known at instant T". The list is
-- generated from config, not from the data, so adding a vintage is a config
-- change rather than a code change.
--
-- Each vintage cuts at the very end of its day, so a request closed at any
-- point on the cutoff date counts as closed at that vintage.

with month_ends as (

    select cast(unnest(generate_series(
        date_trunc('month', cast('{{ var("vintage_first") }}' as date)),
        date_trunc('month', cast('{{ var("build_as_of") }}' as date)),
        interval 1 month
    )) as date) as month_start

),

cutoffs as (

    select
        cast(month_start + interval 1 month - interval 1 day as date) as vintage_date
    from month_ends

),

bounded as (

    -- never generate a vintage past the instant the warehouse was built,
    -- because there is no data to reconstruct it from
    select vintage_date
    from cutoffs
    where vintage_date <= cast('{{ var("build_as_of") }}' as date)

    union

    -- the build instant itself is always the final vintage, so the last
    -- comparison point is current rather than up to a month stale
    select cast('{{ var("build_as_of") }}' as date)

)

select
    vintage_date,
    -- inclusive upper bound of the vintage, the last instant it can see
    cast(vintage_date + interval 1 day - interval 1 second as timestamp) as vintage_cutoff_at,
    row_number() over (order by vintage_date)                           as vintage_seq,
    vintage_date = (select max(vintage_date) from bounded)              as is_final_vintage
from bounded
order by vintage_date
