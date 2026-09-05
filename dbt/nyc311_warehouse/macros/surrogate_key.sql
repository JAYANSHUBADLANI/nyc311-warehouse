{% macro surrogate_key(field_list) %}
{#-
    Deterministic surrogate key from a list of natural key columns.

    Hash rather than row_number, because a row_number surrogate is only stable
    as long as the underlying set and its ordering never change, and both change
    here every time the window moves. Nulls are coalesced to a sentinel so that
    a null and the literal string 'NULL' cannot collide onto the same key.
-#}
    md5(
        {%- for field in field_list %}
        coalesce(cast({{ field }} as varchar), '<<null>>')
        {%- if not loop.last %} || '||' || {% endif %}
        {%- endfor %}
    )
{% endmacro %}
