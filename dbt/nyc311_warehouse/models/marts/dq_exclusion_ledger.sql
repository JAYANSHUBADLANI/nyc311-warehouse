{{ config(materialized='table') }}

-- Reconciliation from landed rows to fact rows, with every difference named.
--
-- The rule this enforces: rows_landed must equal
-- duplicate_ingestions + rows_quarantined + rows_valid, with no residual. If a
-- future change starts dropping rows anywhere between landing and the fact
-- table, the reconciliation line at the bottom stops saying "tie out" and the
-- dq_ledger_reconciles test fails.
--
-- Read the stages in order. Each row is a step, and the deltas are signed so
-- they sum to zero against the residual.

with landed as (
    select
        count(*)                     as rows_landed,
        count(distinct unique_key)   as distinct_requests_landed
    from {{ source('raw', 'service_requests_landing') }}
),

staged as (
    select count(*) as rows_staged from {{ ref('stg_service_requests') }}
),

quarantined as (
    select
        exclusion_reason,
        count(*) as n
    from {{ ref('int_requests_quarantined') }}
    group by 1
),

quarantine_total as (
    select coalesce(sum(n), 0) as rows_quarantined from quarantined
),

valid as (
    select count(*) as rows_valid from {{ ref('int_requests_valid') }}
),

stages as (

    select
        1 as step,
        'landed_rows' as stage,
        'rows written to the landing table by the ingest' as description,
        (select rows_landed from landed) as row_count,
        cast(null as bigint) as delta_from_previous

    union all

    select
        2,
        'deduplicated_to_current_state',
        'landing is an append log, one row kept per request: the latest ingestion',
        (select rows_staged from staged),
        (select rows_staged from staged) - (select rows_landed from landed)

    union all

    select
        3,
        'quarantined',
        'removed for a fatal data quality rule, itemised in the rows below',
        (select rows_quarantined from quarantine_total),
        cast(null as bigint)

    union all

    select
        4,
        'valid_for_fact',
        'rows placed in fct_service_request',
        (select rows_valid from valid),
        (select rows_valid from valid) - (select rows_staged from staged)

    union all

    select
        5,
        'reconciliation_residual',
        'staged minus quarantined minus valid, must be zero',
        (select rows_staged from staged)
            - (select rows_quarantined from quarantine_total)
            - (select rows_valid from valid),
        cast(null as bigint)

),

reasons as (

    select
        10 as step,
        'quarantine_reason: ' || exclusion_reason as stage,
        'count of rows excluded under this rule' as description,
        n as row_count,
        cast(null as bigint) as delta_from_previous
    from quarantined

)

select * from stages
union all
select * from reasons
order by step, stage
