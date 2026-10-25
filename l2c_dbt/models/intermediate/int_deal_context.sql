with associations as (
    select d.deal_id, count(*) filter (where c.company_id is null or c.younium_account_number is null) as unsynced_companies
    from {{ ref('stg_hubspot__deals') }} d,
         unnest(d.company_ids) associated(company_id)
    left join {{ ref('stg_hubspot__companies') }} c using (company_id)
    group by d.deal_id
)
select d.* exclude(owner_id), d.owner_id as source_owner_id,
    {{ resolved_owner('d.owner_id') }} as owner_id,
    {{ fx_rate('d.currency') }} as rate_to_chf,
    {{ trusted('hubspot_deals', 'd') }} as is_trusted,
    coalesce(m.is_matched, false) as is_matched, m.order_number, m.version,
    m.order_record_id, m.order_effective_start, m.order_effective_end,
    m.billing_currency, coalesce(m.has_draft_order, false) as has_draft_order,
    m.duplicate_order_numbers,
    exists (select 1 from {{ ref('stg_younium__orders') }} suspect
            where suspect.hubspot_deal_id = d.deal_id
              and suspect.status <> {{ rule_value('draft_order_status') }}
              and (not exists (select 1 from {{ ref('int_order_versions') }} valid
                               where valid.record_id = suspect.record_id)
                   or exists (select 1 from {{ ref('quarantine') }} q
                              where q.source_table = 'younium_orders'
                                and q.record_id = suspect.record_id))) as has_untrusted_order,
    coalesce(a.unsynced_companies, 0) as unsynced_companies,
    coalesce(li.line_item_count, 0) as line_item_count,
    coalesce(li.unknown_sku_count, 0) as unknown_sku_count,
    coalesce(li.invalid_item_count, 0) as invalid_item_count,
    li.seats as line_item_seats, li.line_item_total, li.unit_price, li.unit_prices
from {{ ref('stg_hubspot__deals') }} d
left join {{ ref('int_deal_order_match') }} m using (deal_id)
left join associations a using (deal_id)
left join {{ ref('int_line_item_totals') }} li using (deal_id)
