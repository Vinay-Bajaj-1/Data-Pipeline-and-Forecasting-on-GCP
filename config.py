from pathlib import Path

# GCP Configuration
PROJECT_ID = "project-5347a2a1-c82e-4585-b74"
TABLE_ID = f"{PROJECT_ID}.finflow.stg_stock_prices"
MAIN_TABLE_ID = f"{PROJECT_ID}.finflow.raw_stock_prices"
BUCKET_NAME = "finflow-raw-804475987385"
LOCATION = "us-central1"

# Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_RAW_DIR = BASE_DIR / "data" / "raw"
MODELS_DIR = BASE_DIR / "models"
OUTPUTS_DIR = BASE_DIR / "outputs"
SQL_DIR = BASE_DIR / "sql"

# Files
MODEL_FILE = MODELS_DIR / "xgboost_return_model.json"
METADATA_FILE = MODELS_DIR / "metadata.json"
FORECASTS_FILE = OUTPUTS_DIR / "latest_forecasts.parquet"
METRICS_FILE = OUTPUTS_DIR / "test_metrics.csv"
PREDICTIONS_FILE = OUTPUTS_DIR / "test_predictions.parquet"

# Stock Universe
SYMBOLS = [
    "RELIANCE.NS",
    "TCS.NS",
    "HDFCBANK.NS",
    "ICICIBANK.NS",
    "INFY.NS",
    "ITC.NS",
    "LT.NS",
    "SBIN.NS",
    "BHARTIARTL.NS",
    "HINDUNILVR.NS",
]

