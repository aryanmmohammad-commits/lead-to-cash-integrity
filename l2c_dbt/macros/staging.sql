{% macro source_specs() %}
  {{ return({
    'hubspot_companies': {'keys': ['company_id'], 'dates': ['created_at'],
      'ids': ['company_id', 'owner_id', 'younium_account_number'], 'domain': 'domain'},
    'hubspot_contacts': {'keys': ['contact_id'], 'dates': ['created_at'],
      'ids': ['contact_id', 'company_id', 'owner_id'], 'email': 'email'},
    'hubspot_deals': {'keys': ['deal_id'], 'dates': ['close_date', 'contract_start', 'contract_end', 'created_at'],
      'numbers': ['amount'], 'integers': ['term_months'], 'ids': ['deal_id', 'owner_id'], 'lists': ['company_ids']},
    'hubspot_line_items': {'keys': ['line_item_id'], 'numbers': ['quantity', 'unit_price', 'amount'],
      'ids': ['line_item_id', 'deal_id']},
    'hubspot_owners': {'keys': ['owner_id'], 'ids': ['owner_id']},
    'younium_accounts': {'keys': ['account_number'], 'ids': ['account_number', 'hubspot_company_id'],
      'domain': 'domain'},
    'younium_orders': {'keys': ['order_number', 'version'],
      'dates': ['effective_start', 'effective_end', 'cancellation_date'], 'integers': ['version', 'term_months'],
      'ids': ['order_number', 'account_number', 'hubspot_deal_id'], 'booleans': ['auto_renew'], 'fx': 'as_of'},
    'younium_order_charges': {'keys': ['charge_id'], 'dates': ['effective_start', 'effective_end'],
      'numbers': ['quantity', 'price', 'mrr'], 'integers': ['version'], 'ids': ['charge_id', 'order_number']},
    'younium_invoices': {'keys': ['invoice_number'], 'numbers': ['amount'],
      'dates': ['service_period_start', 'service_period_end', 'posted_date'],
      'ids': ['invoice_number', 'account_number', 'order_number'], 'booleans': ['is_credit'], 'fx': 'posted_date'},
    'younium_bookings': {'keys': ['booking_id'], 'numbers': ['cmrr_change'], 'dates': ['booking_date'],
      'integers': ['version'], 'ids': ['booking_id', 'order_number'], 'fx': 'booking_date'},
    'ref_fx_rates': {'keys': ['currency', 'date'], 'dates': ['date'], 'numbers': ['rate_to_chf']},
    'ref_product_catalog': {'keys': ['sku'], 'ids': ['sku'], 'numbers': ['list_price'], 'fx': 'as_of'}
  }) }}
{% endmacro %}

{% macro staging_name(table) %}
  {{ return('stg_' ~ table.split('_', 1)[0] ~ '__' ~ table.split('_', 1)[1]) }}
{% endmacro %}

{% macro stage_source(table) %}
  {% set spec = source_specs()[table] %}
  {% set columns = var('mapping')[table]['columns'] %}
  with parsed as (
    select
      {% for column in columns %}
        {% if column in spec.get('dates', []) %}
          {{ parse_date(table, column) }}
        {% elif column in spec.get('integers', []) %}
          {{ parse_integer(table, column) }}
        {% elif column in spec.get('numbers', []) %}
          {{ parse_number(table, column) }}
        {% elif column in spec.get('booleans', []) %}
          try_cast({{ map_value(table, column) }} as boolean)
        {% elif column in spec.get('lists', []) %}
          list_filter(list_transform(string_split(coalesce({{ map_value(table, column) }}, ''), ';'),
            lambda item: nullif(trim(item), '')), lambda item: item is not null)
        {% elif column == spec.get('email') %}
          lower(replace({{ map_value(table, column) }}, ' ', ''))
        {% else %}
          {{ map_value(table, column) }}
        {% endif %} as {{ adapter.quote(column) }},
        {{ src_col(table, column) }} as {{ adapter.quote(column ~ '__raw') }},
      {% endfor %}
      loaded_at, run_id, source_file
    from {{ source('raw', table) }}
  )
  select *,
    {% if spec['keys'] | length == 1 %}
      {{ adapter.quote(spec['keys'][0]) }}
    {% else %}
      concat_ws(':', {% for key in spec['keys'] %}
        coalesce(cast({{ adapter.quote(key) }} as varchar), {{ adapter.quote(key ~ '__raw') }})
        {% if not loop.last %}, {% endif %}{% endfor %})
    {% endif %} as record_id,
    {% if spec.get('domain') %}{{ domain_clean(adapter.quote(spec['domain'])) }} as domain_clean,{% endif %}
    {% if table == 'hubspot_deals' %}
      coalesce(stage = {{ sql_string(var('rules')['closed_won_stage']) }}, false) as is_closed_won,
      coalesce(list_contains({{ string_list(var('rules')['open_deal_stages']) }}, stage), false) as is_open,
    {% endif %}
    true
    {% for column in spec.get('numbers', []) + spec.get('integers', []) + spec.get('dates', []) %}
      and not ({{ map_value(table, column, adapter.quote(column ~ '__raw')) }} is not null
               and {{ adapter.quote(column) }} is null)
    {% endfor %}
    {% for column in spec.get('ids', []) %}
      and not {{ excel_id(adapter.quote(column)) }}
    {% endfor %}
    {% for column in spec.get('lists', []) %}
      and not exists (select 1 from unnest({{ adapter.quote(column) }}) ids(id)
                      where {{ excel_id('ids.id') }})
    {% endfor %}
    as is_parse_valid
  from parsed
{% endmacro %}
