{{ config(severity='error') }}

-- The reconciliation must close exactly.
--
-- Landed rows, less the append log collapse, less quarantine, must equal the
-- fact row count with nothing left over. This is the test that catches a future
-- change that starts dropping rows silently: any WHERE clause added between
-- landing and the fact without a matching ledger entry lands here.

select
    stage,
    row_count
from {{ ref('dq_exclusion_ledger') }}
where stage = 'reconciliation_residual'
  and row_count <> 0
