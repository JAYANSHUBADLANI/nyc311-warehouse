{% macro request_state_as_of(cutoff_expr) %}
{#-
    Reconstructs the state a request was in at a past instant.

    This is the whole trick the project rests on, so it is worth being precise
    about what it can and cannot do.

    What it reconstructs faithfully: anything derivable from the timestamps the
    source maintains. A request created before the cutoff whose close date falls
    after the cutoff was, necessarily, open at the cutoff. Its closed date was
    null then and is populated now. That is a genuine restatement and it is
    recoverable exactly, because both timestamps are still in the row.

    What it cannot reconstruct: any change that overwrites a value in place
    without leaving a timestamp behind. If a ticket was reclassified from one
    complaint type to another, or its descriptor was edited, a single snapshot
    shows only the final value and there is no way to tell from within the
    snapshot that it ever differed. Replayed vintages therefore understate
    dimension churn, and the append only versus merge divergence measured from
    them is a lower bound rather than an estimate.

    That caveat is bounded empirically rather than left as a caveat: the build
    takes two live snapshots of the same requests, at the start and the end, and
    reports what actually changed in the overlap. See
    reports/mutation_probe.md.
-#}
    case
        when closed_at is not null and closed_at <= {{ cutoff_expr }}
        then closed_at
    end as closed_at_vintage,

    case
        when closed_at is not null and closed_at <= {{ cutoff_expr }}
        then 'Closed'
        else 'Open'
    end as status_at_vintage,

    (closed_at is not null and closed_at <= {{ cutoff_expr }}) as is_closed_at_vintage
{% endmacro %}


{% macro days_between(start_expr, end_expr) %}
{#-
    Elapsed days as a fractional number, not a whole day count.

    date_diff('day', ...) counts boundary crossings, so a request opened at
    23:00 and closed at 01:00 the next morning scores a full day while one
    opened at 01:00 and closed at 23:00 the same day scores zero. Over millions
    of rows that is a systematic bias, not noise. Dividing the second difference
    keeps the measure continuous.
-#}
    (date_diff('second', {{ start_expr }}, {{ end_expr }}) / 86400.0)
{% endmacro %}
