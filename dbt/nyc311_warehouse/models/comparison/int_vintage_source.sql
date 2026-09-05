{{ config(materialized='view') }}

-- What the source would have handed an incremental run at one vintage.
--
-- This model is the pipeline's view of the world at a single instant, and both
-- competing fact tables read from it. That is the point of the experiment: the
-- two models are fed byte for byte the same rows, so the only thing that
-- differs between them is what they do on arrival, append or merge. If they
-- were given different source filters the comparison would prove nothing.
--
-- Two vars drive it, set per vintage by scripts/run_vintage_replay.py:
--   vintage_cutoff   the instant this run happens at
--   previous_cutoff  the high water mark left by the previous run
--
-- The batch is what a real incremental pull would ask for: everything whose
-- observable update timestamp moved since the last run. That deliberately
-- includes two different kinds of row, and the distinction is the whole story:
--
--   new rows          created since the last run, seen for the first time
--   restated rows     created before the last run, but closed since it, so
--                     their state at this vintage differs from the state the
--                     pipeline recorded last time
--
-- An append only model handles the first kind correctly and drops the second
-- kind on the floor, because it already holds a row with that key.

with source as (

    select * from {{ ref('int_requests_valid') }}

),

as_of as (

    select
        request_id,
        created_at,

        -- state reconstructed at the cutoff, not current state
        case
            when closed_at is not null
             and closed_at <= cast('{{ var("vintage_cutoff") }}' as timestamp)
            then closed_at
        end as closed_at,

        case
            when closed_at is not null
             and closed_at <= cast('{{ var("vintage_cutoff") }}' as timestamp)
            then 'Closed'
            else 'Open'
        end as status_at_vintage,

        agency_code,
        complaint_type,
        descriptor,
        borough,
        community_board,
        incident_zip

    from source
    where created_at <= cast('{{ var("vintage_cutoff") }}' as timestamp)

),

observable as (

    select
        *,
        -- The update timestamp the source could actually expose at this
        -- vintage. A close that has not happened yet cannot move it.
        greatest(created_at, coalesce(closed_at, created_at)) as source_updated_at,
        (closed_at is not null)                               as is_closed_at_vintage,
        case
            when closed_at is not null
            then {{ days_between('created_at', 'closed_at') }}
        end                                                   as days_to_close_at_vintage
    from as_of

)

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
    cast('{{ var("vintage_cutoff") }}' as timestamp) as loaded_at_vintage
from observable
where
{% if var('previous_cutoff', none) %}
    -- incremental batch: only what changed since the last run
    source_updated_at > cast('{{ var("previous_cutoff") }}' as timestamp)
{% else %}
    -- first vintage, the pipeline has no high water mark yet
    true
{% endif %}
