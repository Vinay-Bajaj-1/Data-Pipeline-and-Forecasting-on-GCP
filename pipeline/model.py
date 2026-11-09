import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
from xgboost import XGBRegressor

from config import (
    FORECASTS_FILE,
    METADATA_FILE,
    METRICS_FILE,
    MODEL_FILE,
    MODELS_DIR,
    OUTPUTS_DIR,
    PREDICTIONS_FILE,
)


class StockModel:
    """Handles feature engineering, XGBoost model training, artifact persistence, and forecasting."""

    FEATURE_COLUMNS = [
        "daily_return",
        "volatility_20d",
        "price_to_ma_5d",
        "price_to_ma_20d",
        "relative_volume_20d",
    ]

    def __init__(self, model_file: Path = MODEL_FILE, metadata_file: Path = METADATA_FILE):
        self.model_file = model_file
        self.metadata_file = metadata_file
        self.model = XGBRegressor()

    def build_features(self, df: pd.DataFrame):
        df = df.copy()
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df["target_date"] = pd.to_datetime(df["target_date"])
        df = df.sort_values(["symbol", "trade_date"])

        df["price_to_ma_5d"] = df["adjusted_close"] / df["moving_average_5d"] - 1
        df["price_to_ma_20d"] = df["adjusted_close"] / df["moving_average_20d"] - 1
        df["relative_volume_20d"] = df["volume"] / df["rolling_volume_20d"].replace(0, float("nan"))

        df[self.FEATURE_COLUMNS] = df[self.FEATURE_COLUMNS].replace([float("inf"), float("-inf")], float("nan"))

        prediction_rows = df.loc[df["target_next_day_return"].isna()].copy()
        required_cols = self.FEATURE_COLUMNS + ["target_next_day_return", "baseline_return_7d", "target_date"]
        eligible = df.dropna(subset=required_cols).copy()

        if eligible.duplicated(["symbol", "trade_date"]).any():
            raise ValueError("Duplicate stock/date records found")

        dates = sorted(eligible["trade_date"].unique())
        if len(dates) < 10:
            raise ValueError("Not enough dates for train/val/test splits")

        validation_start = dates[int(len(dates) * 0.70)]
        test_start = dates[int(len(dates) * 0.85)]

        train = eligible.loc[(eligible["trade_date"] < validation_start) & (eligible["target_date"] < validation_start)].copy()
        validation = eligible.loc[(eligible["trade_date"] >= validation_start) & (eligible["trade_date"] < test_start) & (eligible["target_date"] < test_start)].copy()
        test = eligible.loc[eligible["trade_date"] >= test_start].copy()

        return train, validation, test, prediction_rows

    def train(self, train: pd.DataFrame, validation: pd.DataFrame):
        X_train = train[self.FEATURE_COLUMNS].astype(float)
        y_train = train["target_next_day_return"].astype(float)
        X_val = validation[self.FEATURE_COLUMNS].astype(float)
        y_val = validation["target_next_day_return"].astype(float)

        self.model = XGBRegressor(
            objective="reg:squarederror",
            n_estimators=500,
            learning_rate=0.03,
            max_depth=3,
            min_child_weight=10,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=10,
            tree_method="hist",
            eval_metric="rmse",
            early_stopping_rounds=30,
            random_state=42,
            n_jobs=4,
        )

        self.model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
        return self.model

    def evaluate_test(self, test: pd.DataFrame) -> pd.DataFrame:
        X_test = test[self.FEATURE_COLUMNS].astype(float)
        results = test[["symbol", "trade_date", "target_date", "target_next_day_return", "baseline_return_7d"]].copy()
        results["xgboost_prediction"] = self.model.predict(X_test)
        return results

    def save_artifacts(self, test_results: pd.DataFrame, train: pd.DataFrame, validation: pd.DataFrame, test: pd.DataFrame):
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

        version = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        candidate_dir = MODELS_DIR / 'versions' / version
        candidate_dir.mkdir(parents=True, exist_ok=False)
        self.model_file = candidate_dir / 'xgboost_return_model.json'
        self.metadata_file = candidate_dir / 'metadata.json'
        self.model.save_model(self.model_file)

        metadata = {
            "saved_at_utc": datetime.now(timezone.utc).isoformat(),
            "target": "next_trading_day_return",
            "baseline": "7_trading_day_mean_return",
            "feature_columns": self.FEATURE_COLUMNS,
            "best_tree_count": int(self.model.best_iteration + 1),
            "parameters": self.model.get_params(),
            "splits": {
                name: {
                    "rows": len(frame),
                    "first_date": str(frame["trade_date"].min()),
                    "last_date": str(frame["trade_date"].max()),
                }
                for name, frame in [("train", train), ("validation", validation), ("test", test)]
            },
        }
        self.metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        test_results.to_parquet(candidate_dir / 'test_predictions.parquet', index=False)

        metric_rows = []
        groups = [("Overall", test_results)] + list(test_results.groupby("symbol"))
        for label, frame in groups:
            actual = frame["target_next_day_return"].astype(float)
            for name, col in [("Baseline", "baseline_return_7d"), ("XGBoost", "xgboost_prediction")]:
                pred = frame[col].astype(float)
                metric_rows.append({
                    "symbol": label,
                    "model": name,
                    "mae": mean_absolute_error(actual, pred),
                    "rmse": mean_squared_error(actual, pred) ** 0.5,
                    "rows": len(frame),
                })

        pd.DataFrame(metric_rows).to_csv(candidate_dir / 'test_metrics.csv', index=False)
        reloaded = XGBRegressor()
        reloaded.load_model(self.model_file)
        np.testing.assert_allclose(
            reloaded.predict(test[self.FEATURE_COLUMNS].astype(float)),
            test_results['xgboost_prediction'].to_numpy(), rtol=1e-6, atol=1e-8)
        print(f"Candidate saved and reload verified: {version}. Active model unchanged.")

    def load_model(self):
        if not self.model_file.exists():
            raise FileNotFoundError(f"Model file {self.model_file} not found")
        metadata = json.loads(self.metadata_file.read_text(encoding='utf-8'))
        self.FEATURE_COLUMNS = metadata['feature_columns']
        self.model = XGBRegressor()
        self.model.load_model(self.model_file)
        return self.model

    def generate_latest_forecasts(self, latest_df: pd.DataFrame) -> pd.DataFrame:
        latest = latest_df.sort_values(["symbol", "trade_date"]).groupby("symbol").tail(1).copy()
        from config import SYMBOLS
        if set(latest['symbol']) != set(SYMBOLS):
            raise ValueError('Forecast stocks do not match the configured universe')
        inputs = latest[self.FEATURE_COLUMNS].astype(float)

        if not np.isfinite(inputs.to_numpy()).all():
            raise ValueError("Prediction features contain missing or non-finite values")

        latest["predicted_return"] = self.model.predict(inputs)
        latest["generated_at_utc"] = datetime.now(timezone.utc)
        latest["forecast_horizon"] = "next trading session"

        forecasts = latest[[
            "symbol",
            "trade_date",
            "baseline_return_7d",
            "predicted_return",
            "generated_at_utc",
            "forecast_horizon",
        ]].rename(columns={"trade_date": "as_of_trade_date"})

        OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
        forecasts.to_parquet(FORECASTS_FILE, index=False)
        print("Latest forecasts generated and saved:")
        print(forecasts.to_string(index=False))
        return forecasts

