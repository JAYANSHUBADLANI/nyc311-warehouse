{{ config(materialized='table') }}

-- One row per distinct (borough, community board, zip) combination observed.
--
-- Why a dimension: these three attributes are hierarchical and heavily
-- repeated, they are the natural slicers for any operational view of 311, and
-- holding them once lets the fact carry a single narrow key instead of three
-- wide strings per row. The grain is the combination rather than the zip alone
-- because zips cross borough boundaries in this source, so zip on its own is
-- not a key.
--
-- Type 1. A community board being renumbered is a source correction rather than
-- an analytical event anyone here needs to reconstruct.
--
-- The surrogate key is a hash of the natural key parts, so it is stable across
-- runs. A row_number would renumber whenever the underlying set changed.

with observed as (

    select
        coalesce(borough, 'UNKNOWN')          as borough,
        coalesce(community_board, 'UNKNOWN')  as community_board,
        coalesce(incident_zip, 'UNKNOWN')     as incident_zip,
        count(*)                              as request_count
    from {{ ref('int_requests_valid') }}
    group by 1, 2, 3

)

select
    {{ surrogate_key(['borough', 'community_board', 'incident_zip']) }} as geography_key,

    borough,
    community_board,
    incident_zip,

    -- The source writes several forms of "not known" into borough. Folding them
    -- into one flag keeps the BI layer from showing three different unknowns.
    borough in ('UNKNOWN', 'Unspecified', 'UNSPECIFIED')                as is_borough_unknown,
    incident_zip = 'UNKNOWN'                                            as is_zip_unknown,

    request_count

from observed
