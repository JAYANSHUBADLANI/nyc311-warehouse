{{ config(severity='error') }}

-- The fact must have exactly one row per valid request. Fewer means a join
-- dropped rows, more means a join fanned out, and the SCD2 join is the most
-- likely cause of either.

select
    (select count(*) from {{ ref('fct_service_request') }}) as fact_rows,
    (select count(*) from {{ ref('int_requests_valid') }})  as valid_rows
where (select count(*) from {{ ref('fct_service_request') }})
   <> (select count(*) from {{ ref('int_requests_valid') }})
