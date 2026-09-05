{{ config(materialized='table') }}

-- Calendar spine covering the ingest window plus a year either side.
--
-- Generated from the configured window rather than from observed data, so the
-- dimension has no gaps on days when the city received no requests of a given
-- type. A date dimension built by selecting distinct dates out of the fact
-- table would be missing exactly the quiet days a backlog series needs.
--
-- Bounds come from dbt vars, which are written from config/config.yml. Nothing
-- here calls current_date, so two runs on the same config produce the same rows.

with bounds as (

    select
        date_trunc('year', cast('{{ var("window_start") }}' as timestamp))
            - interval 1 year                                          as start_date,
        date_trunc('year', cast('{{ var("window_end") }}' as timestamp))
            + interval 1 year                                          as end_date

),

spine as (

    select cast(unnest(generate_series(
        (select start_date from bounds),
        (select end_date from bounds),
        interval 1 day
    )) as date) as date_day

)

select
    date_day                                                as date_key,
    date_day,

    extract(year from date_day)                             as calendar_year,
    extract(quarter from date_day)                          as calendar_quarter,
    extract(month from date_day)                            as calendar_month,
    extract(day from date_day)                              as day_of_month,
    extract(dayofweek from date_day)                        as day_of_week,
    extract(dayofyear from date_day)                        as day_of_year,
    extract(week from date_day)                             as iso_week,

    strftime(date_day, '%Y-%m')                             as year_month,
    strftime(date_day, '%B')                                as month_name,
    strftime(date_day, '%A')                                as day_name,

    cast(date_trunc('month', date_day) as date)             as month_start_date,
    cast(date_trunc('quarter', date_day) as date)           as quarter_start_date,
    cast(date_trunc('year', date_day) as date)              as year_start_date,
    cast(date_trunc('week', date_day) as date)              as week_start_date,

    extract(dayofweek from date_day) in (0, 6)              as is_weekend,

    -- Whether this day is inside the window actually ingested. Useful as a
    -- filter in the BI layer, since the spine deliberately extends past it.
    date_day >= cast('{{ var("window_start") }}' as date)
        and date_day <= cast('{{ var("window_end") }}' as date)         as is_in_ingest_window

from spine
order by date_day
