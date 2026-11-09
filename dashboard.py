from datetime import datetime, timezone
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

from config import (
    FORECASTS_FILE,
    METRICS_FILE,
    PREDICTIONS_FILE,
    SYMBOLS,
)
from pipeline.warehouse import BigQueryWarehouse

# Streamlit Page Config
st.set_page_config(
    page_title="FinFlow - Stock Forecasting Dashboard",
    page_icon="📈",
    layout="wide",
)


# Most recent pipeline execution, recorded by train/daily modes.
from config import BASE_DIR
import json
status_path = BASE_DIR / 'logs' / 'latest.json'
if status_path.exists():
    try:
        run = json.loads(status_path.read_text(encoding='utf-8'))
        st.caption(f"Latest pipeline run: {run.get('mode')} | {run.get('status')} | finished {run.get('finished_at', 'not yet')}")
        if run.get('status') == 'failed':
            st.error(f"Pipeline failed: {run.get('error', 'See run log')}")
    except (OSError, ValueError):
        st.warning('Run status temporarily unavailable')


# Cached Data Loaders
@st.cache_data(ttl=60)
def load_forecasts():
    if not FORECASTS_FILE.exists():
        return None
    return pd.read_parquet(FORECASTS_FILE)


@st.cache_data(ttl=60)
def load_metrics():
    if not METRICS_FILE.exists():
        return None
    return pd.read_csv(METRICS_FILE)


@st.cache_data(ttl=60)
def load_predictions():
    if not PREDICTIONS_FILE.exists():
        return None
    return pd.read_parquet(PREDICTIONS_FILE)


@st.cache_data(ttl=300)
def fetch_stock_history(symbol: str, start_date: str, end_date: str):
    warehouse = BigQueryWarehouse()
    return warehouse.query_stock_history(symbol, start_date, end_date)


# Header
st.title("📈 FinFlow - Stock Forecasting Dashboard")

# Navigation Tabs: Forecasts first
tab_forecasts, tab_eval, tab_explorer = st.tabs([
    "🎯 Forecasts",
    "📊 Model Evaluation",
    "🔍 Stock Explorer"
])

# -------------------------------------------------------------
# TAB 1: FORECASTS
# -------------------------------------------------------------
with tab_forecasts:
    st.subheader("Next Trading-Session Return Forecasts")
    df_forecasts = load_forecasts()

    if df_forecasts is None or df_forecasts.empty:
        st.error("Missing file: `outputs/latest_forecasts.parquet` was not found. Please run the daily pipeline first.")
    else:
        # Check staleness
        if "generated_at_utc" in df_forecasts.columns:
            gen_time = pd.to_datetime(df_forecasts["generated_at_utc"]).max()
            now_utc = datetime.now(timezone.utc)
            hours_old = (now_utc - gen_time).total_seconds() / 3600.0

            if hours_old > 24:
                st.warning(
                    f"⚠️ Stale Forecast Data: Generated {hours_old:.1f} hours ago on "
                    f"{gen_time.strftime('%Y-%m-%d %H:%M UTC')}. Consider running the daily pipeline."
                )
            else:
                st.info(f"ℹ️ Generated on {gen_time.strftime('%Y-%m-%d %H:%M UTC')} (Latest)")

        # Prepare formatted display table
        df_display = df_forecasts.copy()
        df_display["Next Trading-Session Return"] = df_display["predicted_return"].apply(lambda x: f"{x * 100:+.2f}%")
        df_display["7-Day Baseline Return"] = df_display["baseline_return_7d"].apply(lambda x: f"{x * 100:+.2f}%")

        if "as_of_trade_date" in df_display.columns:
            df_display["As of Trade Date"] = pd.to_datetime(df_display["as_of_trade_date"]).dt.strftime('%Y-%m-%d')
        elif "trade_date" in df_display.columns:
            df_display["As of Trade Date"] = pd.to_datetime(df_display["trade_date"]).dt.strftime('%Y-%m-%d')

        df_display = df_display.sort_values(by="predicted_return", ascending=False)

        cols_to_show = ["symbol", "As of Trade Date", "Next Trading-Session Return", "7-Day Baseline Return", "forecast_horizon"]
        cols_to_show = [c for c in cols_to_show if c in df_display.columns]

        st.dataframe(
            df_display[cols_to_show].rename(columns={"symbol": "Stock", "forecast_horizon": "Horizon"}),
            use_container_width=True,
            hide_index=True,
        )

        # Bar chart comparison
        fig_bar = px.bar(
            df_forecasts.sort_values(by="predicted_return", ascending=False),
            x="symbol",
            y="predicted_return",
            color="predicted_return",
            color_continuous_scale="RdYlGn",
            labels={"symbol": "Stock", "predicted_return": "Predicted Return"},
            title="Predicted Next Trading-Session Return by Stock"
        )
        fig_bar.layout.yaxis.tickformat = '.2%'
        st.plotly_chart(fig_bar, use_container_width=True)


# -------------------------------------------------------------
# TAB 2: MODEL EVALUATION
# -------------------------------------------------------------
with tab_eval:
    st.subheader("Model Evaluation & Benchmark Comparison")
    df_metrics = load_metrics()
    df_preds = load_predictions()

    if df_metrics is None or df_metrics.empty:
        st.error("Missing file: `outputs/test_metrics.csv` was not found. Please train the model first.")
    else:
        df_m_disp = df_metrics.copy()
        df_m_disp["MAE (%)"] = df_m_disp["mae"].apply(lambda x: f"{x * 100:.3f}%")
        df_m_disp["RMSE (%)"] = df_m_disp["rmse"].apply(lambda x: f"{x * 100:.3f}%")

        st.markdown("#### Test Set Performance Summary")
        st.dataframe(
            df_m_disp[["symbol", "model", "MAE (%)", "RMSE (%)", "rows"]].rename(
                columns={"symbol": "Stock / Scope", "model": "Model", "rows": "Test Samples"}
            ),
            use_container_width=True,
            hide_index=True,
        )

        fig_m = px.bar(
            df_metrics,
            x="symbol",
            y="mae",
            color="model",
            barmode="group",
            labels={"symbol": "Stock", "mae": "Mean Absolute Error (MAE)"},
            title="Baseline vs XGBoost MAE (Lower is Better)"
        )
        fig_m.layout.yaxis.tickformat = '.3%'
        st.plotly_chart(fig_m, use_container_width=True)

    if df_preds is not None and not df_preds.empty:
        st.markdown("---")
        st.markdown("#### Historical Predictions vs Actuals on Test Set")
        symbols_available = sorted(df_preds["symbol"].unique())
        selected_stock = st.selectbox("Select Stock for Historical Evaluation", symbols_available)

        df_stock_preds = df_preds[df_preds["symbol"] == selected_stock].sort_values("trade_date")

        fig_pred = go.Figure()
        fig_pred.add_trace(go.Scatter(
            x=df_stock_preds["trade_date"],
            y=df_stock_preds["target_next_day_return"],
            mode="lines",
            name="Actual Return",
            line=dict(color="gray", width=1.5)
        ))
        fig_pred.add_trace(go.Scatter(
            x=df_stock_preds["trade_date"],
            y=df_stock_preds["xgboost_prediction"],
            mode="lines",
            name="XGBoost Prediction",
            line=dict(color="#1f77b4", width=2)
        ))
        fig_pred.add_trace(go.Scatter(
            x=df_stock_preds["trade_date"],
            y=df_stock_preds["baseline_return_7d"],
            mode="lines",
            name="7D Baseline",
            line=dict(color="#ff7f0e", dash="dot")
        ))
        fig_pred.update_layout(
            title=f"{selected_stock} - Actual vs Predicted Next-Session Return",
            xaxis_title="Trade Date",
            yaxis_title="Return",
            yaxis_tickformat=".2%",
            hovermode="x unified",
        )
        st.plotly_chart(fig_pred, use_container_width=True)


# -------------------------------------------------------------
# TAB 3: STOCK EXPLORER (BIGQUERY)
# -------------------------------------------------------------
with tab_explorer:
    st.subheader("BigQuery Stock Explorer")
    st.caption("Directly queries only the selected stock and date range from `raw_stock_prices` in BigQuery.")

    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        sel_symbol = st.selectbox("Stock Symbol", SYMBOLS, index=0)
    with col2:
        date_range = st.date_input(
            "Select Date Range",
            value=[datetime(2025, 1, 1).date(), datetime.now().date()]
        )
    with col3:
        st.write("")
        st.write("")
        btn_query = st.button("Load Data", type="primary")

    if btn_query or ("history_df" in st.session_state and st.session_state.get("history_symbol") == sel_symbol):
        if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
            s_date, e_date = date_range[0], date_range[1]
            try:
                with st.spinner(f"Querying BigQuery for {sel_symbol}..."):
                    df_history = fetch_stock_history(sel_symbol, str(s_date), str(e_date))
                    st.session_state["history_df"] = df_history
                    st.session_state["history_symbol"] = sel_symbol
            except Exception as e:
                st.error(f"Error querying BigQuery: {e}")
                df_history = pd.DataFrame()
        else:
            st.warning("Please select both a start and end date.")
            df_history = pd.DataFrame()

    if "history_df" in st.session_state and not st.session_state["history_df"].empty:
        df_hist = st.session_state["history_df"]
        st.success(f"Loaded {len(df_hist)} rows for {st.session_state['history_symbol']}.")

        fig_price = go.Figure(data=[go.Candlestick(
            x=df_hist['trade_date'],
            open=df_hist['open'],
            high=df_hist['high'],
            low=df_hist['low'],
            close=df_hist['close'],
            name="OHLC"
        )])
        fig_price.update_layout(
            title=f"{st.session_state['history_symbol']} Price Action",
            xaxis_title="Date",
            yaxis_title="Price (INR)",
            xaxis_rangeslider_visible=False
        )
        st.plotly_chart(fig_price, use_container_width=True)

        with st.expander("View Raw BigQuery Records"):
            st.dataframe(df_hist, use_container_width=True)
