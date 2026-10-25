select li.deal_id, count(*) as line_item_count,
    count(*) filter (where p.sku is null) as unknown_sku_count,
    count(*) filter (where not {{ trusted('hubspot_line_items', 'li') }}
                      or li.quantity is null or li.unit_price is null or li.amount is null) as invalid_item_count,
    sum(li.quantity) as seats, sum(li.amount) as line_item_total,
    case when count(distinct li.unit_price) = 1 then min(li.unit_price) end as unit_price,
    list(distinct li.unit_price order by li.unit_price) as unit_prices
from {{ ref('stg_hubspot__line_items') }} li
left join {{ ref('stg_ref__product_catalog') }} p on p.sku = li.sku
  and {{ trusted('ref_product_catalog', 'p') }}
group by li.deal_id
