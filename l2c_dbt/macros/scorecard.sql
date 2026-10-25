{% macro denominator_queries() %}
  {{ return({
    'contacts': 'select count(*) from ' ~ ref('stg_hubspot__contacts'),
    'companies': 'select count(*) from ' ~ ref('stg_hubspot__companies'),
    'accounts': 'select count(*) from ' ~ ref('stg_younium__accounts'),
    'closedwon_deals': 'select count(*) from ' ~ ref('stg_hubspot__deals') ~ ' where is_closed_won',
    'won_deals': 'select count(*) from ' ~ ref('stg_hubspot__deals') ~ ' where is_closed_won',
    'open_deals': 'select count(*) from ' ~ ref('stg_hubspot__deals') ~ ' where is_open',
    'new_won_deals': 'select count(*) from ' ~ ref('stg_hubspot__deals') ~ ' where is_closed_won and motion = ' ~ rule_value('new_deal_motion'),
    'change_won_deals': 'select count(*) from ' ~ ref('stg_hubspot__deals') ~ ' where is_closed_won and list_contains(' ~ string_list(rule('change_deal_motions')) ~ ', motion)',
    'deals_and_companies': 'select (select count(*) from ' ~ ref('stg_hubspot__deals') ~ ') + (select count(*) from ' ~ ref('stg_hubspot__companies') ~ ')',
    'push_candidates': 'select count(*) from ' ~ ref('push_readiness'),
    'active_orders': 'select count(*) from ' ~ ref('int_order_financials') ~ ' where is_current and status = ' ~ rule_value('active_order_status'),
    'posted_invoices': 'select count(*) from ' ~ ref('stg_younium__invoices') ~ ' where not is_credit and status = ' ~ rule_value('posted_invoice_status'),
    'new_deals_with_order': 'select count(*) from ' ~ ref('int_deal_context') ~ ' where is_matched and motion = ' ~ rule_value('new_deal_motion'),
    'changed_versions': 'select count(*) from ' ~ ref('stg_younium__orders') ~ ' where version > ' ~ rule('initial_order_version'),
    'cancelled_accounts': 'select count(distinct account_number) from ' ~ ref('stg_younium__orders') ~ ' where status = ' ~ rule_value('cancelled_order_status')
  }) }}
{% endmacro %}

{% test nonnegative(model, column_name) %}
select * from {{ model }} where {{ adapter.quote(column_name) }} < 0
{% endtest %}

{% test probability(model, column_name) %}
select * from {{ model }} where {{ adapter.quote(column_name) }} not between 0 and 1
{% endtest %}
