{#
    Use the schema configured on the model verbatim, rather than dbt's default
    of prefixing it with the target schema.

    Without this override a model configured into "marts" lands in
    "main_marts", because the default macro concatenates target.schema with the
    custom name. Every script in scripts/ addresses these tables as marts.x,
    intermediate.x and comparison.x, which is the naming the models themselves
    declare in dbt_project.yml, so the override makes the warehouse match the
    names the rest of the project already uses.

    A model with no custom schema still lands in target.schema, which is main.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
