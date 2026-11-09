from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
import yfinance as yf
from google.cloud import storage

from config import BUCKET_NAME, DATA_RAW_DIR, SYMBOLS


class DataIngestion:
    """Handles downloading market data from Yahoo Finance and uploading to Google Cloud Storage."""

    def __init__(self, bucket_name: str = BUCKET_NAME, raw_dir: Path = DATA_RAW_DIR):
        self.bucket_name = bucket_name
        self.raw_dir = raw_dir
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def download_stock(self, symbol: str, batch_id: str, ingested_at: datetime, start_date: str, end_date: str):
        df = yf.download(
            symbol,
            start=start_date,
            end=end_date,
            interval="1d",
            auto_adjust=False,
            multi_level_index=False,
            progress=False,
            timeout=30,
        )

        if df is None or df.empty:
            raise ValueError(f"No Data to download for {symbol}")

        df = df.reset_index().rename(columns={
            "Date": "trade_date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Adj Close": "adjusted_close",
            "Volume": "volume",
        })

        df["trade_date"] = df["trade_date"].dt.date
        df["symbol"] = symbol
        df["ingested_at"] = ingested_at
        df["batch_id"] = batch_id

        df = df[[
            "symbol",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "adjusted_close",
            "volume",
            "ingested_at",
            "batch_id",
        ]]

        output_file = self.raw_dir / f"{symbol}_{end_date}_{batch_id}.parquet"
        df.to_parquet(output_file, index=False)
        return output_file, len(df)

    def validate_local_batch(self, batch_id: str, symbols: list[str]) -> int:
        files = sorted(self.raw_dir.glob(f"*_{batch_id}.parquet"))
        if len(files) != len(symbols):
            raise ValueError(f"Expected {len(symbols)} files, found {len(files)}")

        total_rows = 0
        for file in files:
            df = pd.read_parquet(file)
            if df is None or df.empty:
                raise ValueError(f"{file.name} is empty")
            if df.isna().any().any():
                raise ValueError(f"{file.name} contains NaN values")
            if df.duplicated(subset=["symbol", "trade_date"]).any():
                raise ValueError(f"{file.name} contains duplicate dates")

            valid_prices = (
                (df["low"] <= df["open"])
                & (df["open"] <= df["high"])
                & (df["low"] <= df["close"])
                & (df["close"] <= df["high"])
            )
            if not valid_prices.all():
                raise ValueError(f"Invalid price ranges in {file.name}")
            if (df["volume"] < 0).any():
                raise ValueError(f"Negative volume in {file.name}")

            total_rows += len(df)

        return total_rows

    def download_all(self, batch_id: str, ingested_at: datetime, latest_dates: dict[str, any], symbols: list[str] = SYMBOLS) -> int:
        history_start = datetime(2020, 1, 1).date()
        today_ist = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()

        errors = []
        for symbol in symbols:
            last_date = latest_dates.get(symbol)
            try:
                start_date = max(history_start, last_date - timedelta(days=7)) if last_date is not None else history_start
                start_date = start_date.isoformat()
                file_path, row_count = self.download_stock(
                    symbol=symbol,
                    batch_id=batch_id,
                    ingested_at=ingested_at,
                    start_date=start_date,
                    end_date=today_ist,
                )
                print(f"Downloaded {symbol}: {row_count} rows -> {file_path.name}")
            except Exception as e:
                errors.append(f"Failed to download {symbol}: {e}")

        if errors:
            raise RuntimeError(f"Batch {batch_id} incomplete:\n" + "\n".join(errors))

        return self.validate_local_batch(batch_id=batch_id, symbols=symbols)

    def upload_to_gcs(self, storage_client: storage.Client, batch_id: str) -> list[str]:
        files = sorted(self.raw_dir.glob(f"*_{batch_id}.parquet"))
        if not files:
            raise FileNotFoundError(f"Files not found for batch_id {batch_id}")

        bucket = storage_client.bucket(self.bucket_name)
        uploaded_uris = []
        for file in files:
            object_name = f"raw/stocks/{file.name}"
            blob = bucket.blob(object_name)
            blob.upload_from_filename(
                str(file),
                content_type="application/octet-stream",
                if_generation_match=0,
            )
            uri = f"gs://{self.bucket_name}/{object_name}"
            uploaded_uris.append(uri)
            print(f"Uploaded: {uri}")

        return uploaded_uris

