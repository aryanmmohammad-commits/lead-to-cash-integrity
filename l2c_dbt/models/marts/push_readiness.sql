with evaluated as (
    select d.deal_id, d.owner_id,
      list_filter([
        case when len(company_ids) <> 1 then {{ sql_string(rule('push_check_ids')['company_count']) }} end,
        case when len(company_ids) = 0 or unsynced_companies > 0 then {{ sql_string(rule('push_check_ids')['account_number']) }} end,
        case when line_item_count = 0 or unknown_sku_count > 0 then {{ sql_string(rule('push_check_ids')['skus']) }} end,
        case when contract_start is null or term_months is null or billing_frequency is null or currency is null
             then {{ sql_string(rule('push_check_ids')['required_fields']) }} end,
        case when amount is null or line_item_count = 0 or invalid_item_count > 0
               or (amount = 0 and coalesce(line_item_total, 0) <> 0)
               or (amount <> 0 and round(abs(line_item_total - amount) / abs(amount) * 100,
                   {{ rule('amount_comparison_decimals') }}) > {{ rule('push_line_item_tolerance_pct') }})
             then {{ sql_string(rule('push_check_ids')['line_total']) }} end
      ], reason -> reason is not null) as reasons
    from {{ ref('int_deal_context') }} d
    where is_closed_won and motion = {{ rule_value('new_deal_motion') }}
      and not is_matched and not has_untrusted_order
)
select deal_id, owner_id,
    case when len(reasons) = 0 then {{ rule_value('push_ready_status') }}
         else {{ rule_value('push_blocked_status') }} end as status, reasons
from evaluated
