{% macro rule(name) %}{{ return(var('rules')[name]) }}{% endmacro %}
{% macro rule_value(name) %}{{ return(sql_string(rule(name))) }}{% endmacro %}

{% macro resolved_owner(expression) %}
  case when exists (select 1 from {{ ref('stg_hubspot__owners') }} owners
                    where owners.owner_id = {{ expression }})
       then {{ expression }} else {{ rule_value('unassigned_owner_id') }} end
{% endmacro %}

{% macro trusted(table, alias) %}
  not exists (select 1 from {{ ref('quarantine') }} q
              where q.source_table = {{ sql_string(table) }} and q.record_id = {{ alias }}.record_id)
{% endmacro %}

{% macro fx_rate(currency, at_date=none) %}
  {% set at_date = at_date if at_date is not none else as_of_date() %}
  (select fx.rate_to_chf from {{ ref('int_fx') }} fx
   where fx.currency = {{ currency }} and fx.effective_start <= {{ at_date }}
     and (fx.effective_end is null or {{ at_date }} < fx.effective_end))
{% endmacro %}

{% macro finding(check_id, object_type, record_id, owner, reason, details, money='null', severity=none) %}
  {{ sql_string(check_id) }}::varchar as check_id,
  {% if severity is none %}
    {{ sql_string(rule('check_catalog')[check_id]['severity']) }}
  {% else %}{{ severity }}{% endif %}::varchar as severity,
  {{ sql_string(object_type) }}::varchar as object_type,
  cast({{ record_id }} as varchar) as record_id,
  cast({{ owner }} as varchar) as owner_id,
  {{ reason }}::varchar as reason,
  cast(to_json({{ details }}) as varchar) as details,
  cast(round({{ money }}, 2) as decimal(38, 2)) as money_at_risk_chf
{% endmacro %}

{% macro proposal_property(table, column) %}
  {% set properties = var('mapping')[table].get('properties', {}) %}
  {% if column not in properties %}
    {{ exceptions.raise_compiler_error('mapping.' ~ table ~ '.properties.' ~ column ~ ' is missing') }}
  {% endif %}
  {{ return(sql_string(properties[column])) }}
{% endmacro %}

{% macro check_models() %}
  {{ return({
    'A1':'chk_a1_lifecycle_invalid','A2':'chk_a2_lifecycle_evidence','A3':'chk_a3_lead_status',
    'A4':'chk_a4_original_source','A5':'chk_a5_won_amount','A6':'chk_a6_contract_fields',
    'A7':'chk_a7_company_domains','A8':'chk_a8_stale_deals','A9':'chk_a9_company_fields',
    'A10':'chk_a10_contact_emails','A11':'chk_a11_contact_company','A12':'chk_a12_contract_dates',
    'A13':'chk_a13_owners','P':'chk_p_push_readiness','R1':'chk_r1_won_not_billed',
    'R2':'chk_r2_billing_without_crm','R3':'chk_r3_value_mismatch','R4':'chk_r4_start_dates',
    'R5':'chk_r5_seats','R6':'chk_r6_unbilled_changes','R7':'chk_r7_renewals',
    'R8':'chk_r8_cancelled_invoices','R9':'chk_r9_duplicate_push','R10':'chk_r10_billing_changes',
    'R11':'chk_r11_cancelled_customers','R12':'chk_r12_duplicate_accounts'
  }) }}
{% endmacro %}
