select * from {{ ref('audit_scorecard') }}
where rows_checked < 0 or rows_failed < 0 or rows_failed > rows_checked
