{% macro src_col(table, canonical) -%}
  {% set tables = var('mapping') %}
  {% if table not in tables or canonical not in tables[table]['columns'] %}
    {{ exceptions.raise_compiler_error('mapping.' ~ table ~ '.columns.' ~ canonical ~ ' is missing') }}
  {% endif %}
  {{ return(adapter.quote(tables[table]['columns'][canonical])) }}
{%- endmacro %}

{% macro generate_schema_name(custom_schema_name, node) -%}
  {% set schema = custom_schema_name if custom_schema_name is not none else target.schema %}
  {% if schema | lower in ['raw', 'state'] %}
    {{ exceptions.raise_compiler_error('raw and state are owned by Python; dbt may not write them') }}
  {% endif %}
  {{ return(schema) }}
{%- endmacro %}

{% macro sql_string(value) -%}
  {{ return("'" ~ (value | string).replace("'", "''") ~ "'") }}
{%- endmacro %}

{% macro text_value(expression) -%}
  nullif(trim(cast({{ expression }} as varchar)), '')
{%- endmacro %}

{% macro map_value(table, canonical, expression=none) -%}
  {% set expression = expression if expression is not none else src_col(table, canonical) %}
  {% set values = var('mapping')[table].get('values', {}).get(canonical, {}) %}
  {% if values %}
    case {{ text_value(expression) }}
      {% for label, internal in values.items() %}
      when {{ sql_string(label) }} then {{ sql_string(internal) }}
      {% endfor %}
      else {{ text_value(expression) }}
    end
  {% else %}
    {{ text_value(expression) }}
  {% endif %}
{%- endmacro %}

{% macro parse_number(table, canonical, expression=none) -%}
  {% set expression = map_value(table, canonical, expression) %}
  {% set format = var('mapping')[table]['format'] %}
  {% if format['thousands'] %}
    {% set expression = 'replace(' ~ expression ~ ', ' ~ sql_string(format['thousands']) ~ ", '')" %}
  {% endif %}
  {% if format['decimal'] != '.' %}
    {% set expression = 'replace(' ~ expression ~ ', ' ~ sql_string(format['decimal']) ~ ", '.')" %}
  {% endif %}
  try_cast({{ expression }} as decimal(38, 12))
{%- endmacro %}

{% macro parse_integer(table, canonical, expression=none) -%}
  {% set number = parse_number(table, canonical, expression) %}
  case when {{ number }} = trunc({{ number }}) then try_cast({{ number }} as bigint) end
{%- endmacro %}

{% macro parse_date(table, canonical, expression=none) -%}
  cast(try_strptime({{ map_value(table, canonical, expression) }},
                   {{ sql_string(var('mapping')[table]['format']['date_format']) }}) as date)
{%- endmacro %}

{% macro domain_clean(expression) -%}
  nullif(split_part(regexp_replace(regexp_replace(lower({{ text_value(expression) }}),
      '^https?://', ''), '^www[.]', ''), '/', 1), '')
{%- endmacro %}

{% macro excel_id(expression) -%}
  coalesce(regexp_full_match({{ text_value(expression) }},
      '[-+]?[0-9]+([.][0-9]+)?[eE][-+]?[0-9]+'), false)
{%- endmacro %}

{% macro string_list(values) -%}
  [ {% for value in values %}{{ sql_string(value) }}{% if not loop.last %}, {% endif %}{% endfor %} ]
{%- endmacro %}

{% macro as_of_date() -%}
  cast({{ sql_string(var('rules')['as_of_date']) }} as date)
{%- endmacro %}
