CREATE OR REPLACE TABLE
  `{project_id}.finflow.stock_features`
PARTITION BY trade_date
CLUSTER BY symbol
AS


  with returns as (
    select 
    symbol,
    trade_date,
    volume,
    adjusted_close,
    Safe_divide(adjusted_close, lag(adjusted_close) over(partition by symbol order by trade_date)) - 1 as daily_return
    from `{project_id}.finflow.raw_stock_prices`

  )


select 
  symbol, 
  trade_date,
  volume, 
  daily_return,
  adjusted_close,

  CASE
    WHEN COUNT(daily_return) OVER lag_20 = 20
    THEN STDDEV_SAMP(daily_return) OVER lag_20
    end as volatility_20d,

  CASE 
    WHEN COUNT(volume) over lag_20 = 20
    THEN AVG(volume) over lag_20
    end as rolling_volume_20d,


  CASE 
    WHEN COUNT(volume) over lag_5 = 5
    THEN AVG(volume) over lag_5
    end as rolling_volume_5d,


  CASE
      WHEN COUNT(adjusted_close) OVER lag_5 = 5
      THEN AVG(adjusted_close) OVER lag_5
  END AS moving_average_5d,

  CASE
      WHEN COUNT(adjusted_close) OVER lag_20 = 20
      THEN AVG(adjusted_close) OVER lag_20
  END AS moving_average_20d

  from returns

  WINDOW 
    lag_20 as (
      partition by symbol
      order by trade_date
      ROWS between 19 PRECEDING and CURRENT row
    ),

  lag_5 as (
    partition by symbol
    order by trade_date
    ROWS between 4 PRECEDING and CURRENT row
  )

  #order by symbol, trade_date
