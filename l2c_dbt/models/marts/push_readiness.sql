with candidates as (
    select d.*,
      date_diff('day', contract_start, {{ as_of_date() }}) as days_since_contract_start,
      round(abs(line_item_total - amount) / nullif(abs(amount), 0) * 100,
            {{ rule('amount_comparison_decimals') }}) as line_item_gap_pct,
      list_filter([
        case when contract_start is null then 'contract start' end,
        case when term_months is null then 'term months' end,
        case when billing_frequency is null then 'billing frequency' end,
        case when currency is null then 'currency' end
      ], lambda field: field is not null) as missing_fields
    from {{ ref('int_deal_context') }} d
    where is_closed_won and motion = {{ rule_value('new_deal_motion') }}
      and not is_matched and not has_untrusted_order
), evaluated as (
    select *,
      list_filter([
        case when len(company_ids) <> 1 then {{ sql_string(rule('push_check_ids')['company_count']) }} end,
        case when len(company_ids) = 0 or unsynced_companies > 0 then {{ sql_string(rule('push_check_ids')['account_number']) }} end,
        case when line_item_count = 0 or unknown_sku_count > 0 then {{ sql_string(rule('push_check_ids')['skus']) }} end,
        case when len(missing_fields) > 0 then {{ sql_string(rule('push_check_ids')['required_fields']) }} end,
        case when amount is null or line_item_count = 0 or invalid_item_count > 0
               or (amount = 0 and coalesce(line_item_total, 0) <> 0)
               or line_item_gap_pct > {{ rule('push_line_item_tolerance_pct') }}
             then {{ sql_string(rule('push_check_ids')['line_total']) }} end
      ], lambda check_id: check_id is not null) as failed_checks,
      list_filter([
        case when len(company_ids) <> 1
             then 'deal has ' || len(company_ids) || ' associated companies' end,
        case when len(company_ids) = 0 then 'deal has no associated company with a Younium account number'
             when unsynced_companies = 1 then 'an associated company is missing a Younium account number'
             when unsynced_companies > 1 then unsynced_companies || ' associated companies are missing Younium account numbers' end,
        case when line_item_count = 0 then 'deal has no line items'
             when unknown_sku_count = 1 then 'a line item has a SKU missing from the product catalog'
             when unknown_sku_count > 1 then unknown_sku_count || ' line items have SKUs missing from the product catalog' end,
        case when len(missing_fields) > 0
             then 'missing required fields: ' || array_to_string(missing_fields, ', ') end,
        case when amount is null then 'deal amount is blank or unparseable'
             when line_item_count = 0 then 'line-item total is missing because the deal has no line items'
             when invalid_item_count > 0 then 'line-item quantity, price or amount is missing or unparseable'
             when amount = 0 and coalesce(line_item_total, 0) <> 0 then 'line-item total differs from a zero deal amount'
             when line_item_gap_pct > {{ rule('push_line_item_tolerance_pct') }}
               then 'line-item total differs from deal amount by ' || line_item_gap_pct
                    || '% (tolerance ' || cast({{ rule('push_line_item_tolerance_pct') }} as varchar) || '%)' end
      ], lambda reason: reason is not null) as failure_reasons
    from candidates
), classified as (
    select *,
      case when has_draft_order then {{ rule_value('push_draft_only_status') }}
           when days_since_contract_start > {{ rule('won_not_billed_days') }} then {{ rule_value('push_overdue_status') }}
           when len(failed_checks) > 0 then {{ rule_value('push_blocked_status') }}
           else {{ rule_value('push_ready_status') }} end as status
    from evaluated
)
select deal_id, owner_id, days_since_contract_start, status, failed_checks,
    list_concat(failure_reasons,
      case when status = {{ rule_value('push_draft_only_status') }} then ['only a Draft billing order exists']
           when status = {{ rule_value('push_overdue_status') }}
             then ['contract started ' || days_since_contract_start || ' days ago; billing grace period is '
                   || {{ rule('won_not_billed_days') }} || ' days']
           else []::varchar[] end) as reasons
from classified
order by list_position({{ string_list(rule('push_status_order')) }}, status),
         days_since_contract_start desc nulls last, deal_id
