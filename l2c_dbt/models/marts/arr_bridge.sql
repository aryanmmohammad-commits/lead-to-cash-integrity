with categories as (
    select unnest({{ string_list(rule('arr_bridge_categories')) }}) as category
), contributions as (
    select category, sum(amount_chf) as amount_chf
    from {{ ref('int_arr_bridge_ledger') }} group by category
)
select last_day({{ as_of_date() }})::date as month_end, c.category,
    coalesce(v.amount_chf, 0)::decimal(38,2) as amount_chf
from categories c left join contributions v using (category)
