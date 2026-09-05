{{ config(materialized='table', schema='comparison') }}

-- The headline table: how wrong the append only pipeline was, at each vintage.
--
-- Built from comparison.vintage_drift_log, which scripts/run_vintage_replay.py
-- writes one row into after each replayed vintage. The merge table is the
-- reference, and that is a fair reference rather than a rigged one: both models
-- were handed exactly the same source rows at exactly the same instants, so
-- whatever merge holds is what a correct pipeline knows at that vintage.
--
-- Worth saying plainly, because overselling this would be the easiest way to
-- make the whole project untrustworthy: that append only misses restatement is
-- true by construction, not a discovery. The design guarantees the sign of the
-- error. What is genuinely not known in advance, and what this table is for, is
-- the size of the error and how it behaves as vintages accumulate.

with log as (

    select * from {{ source('comparison', 'vintage_drift_log') }}

)

select
    vintage_seq,
    vintage_date,

    append_row_count,
    merge_row_count,
    merge_row_count - append_row_count                        as row_count_gap,

    append_closed_count,
    merge_closed_count,
    merge_closed_count - append_closed_count                  as closures_gap,

    closures_missed_by_append,
    rows_disagreeing,

    -- share of the closures a correct pipeline knows about that the append
    -- only pipeline is unaware of
    cast(closures_missed_by_append as double)
        / nullif(merge_closed_count, 0)                       as share_of_closures_missed,

    -- the closure rate each pipeline would have published at this vintage
    cast(append_closed_count as double)
        / nullif(append_row_count, 0)                         as append_closure_rate,
    cast(merge_closed_count as double)
        / nullif(merge_row_count, 0)                          as merge_closure_rate,
    (cast(append_closed_count as double) / nullif(append_row_count, 0))
        - (cast(merge_closed_count as double) / nullif(merge_row_count, 0))
                                                              as closure_rate_error,

    -- and the mean resolution time each would have published
    append_avg_days_to_close,
    merge_avg_days_to_close,
    append_avg_days_to_close - merge_avg_days_to_close         as avg_days_error,
    case
        when merge_avg_days_to_close > 0
        then (append_avg_days_to_close - merge_avg_days_to_close) / merge_avg_days_to_close
    end                                                        as avg_days_error_pct

from log
order by vintage_seq
