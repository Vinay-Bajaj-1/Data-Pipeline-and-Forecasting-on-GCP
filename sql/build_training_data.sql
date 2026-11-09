select 
symbol, 
trade_date,
daily_return,
volume,
adjusted_close,
moving_average_5d,
moving_average_20d,
volatility_20d,
rolling_volume_20d,
rolling_volume_5d,

LEAD(daily_return) OVER(partition by symbol order by trade_date) as target_next_day_return,
LEAD(trade_date) OVER(partition by symbol order by trade_date) as target_date,

CASE
  WHEN Count(daily_return) OVER lag_7 = 7
  THEN avg(daily_return) OVER lag_7
  END as baseline_return_7d
from `{project_id}.finflow.stock_features`

window lag_7 as (
  partition by symbol order by trade_date
  ROWS between 6 PRECEDING and Current Row
)