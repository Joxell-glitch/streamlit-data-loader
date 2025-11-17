import pandas as pd
import numpy as np

def detect_gaps(df, expected_freq):
    df = df.sort_values("timestamp").copy()
    full = pd.date_range(df["timestamp"].min(), df["timestamp"].max(), freq=expected_freq)
    missing = full.difference(df["timestamp"])
    return pd.DataFrame({"missing_timestamp": missing})

def detect_duplicates(df):
    if df is None:
        return pd.DataFrame()

    if len(df) == 0:
        return df.copy()

    if "timestamp" not in df.columns:
        # Return an empty frame with the same columns to avoid KeyError downstream
        return df.iloc[0:0].copy()

    dup = df["timestamp"].duplicated(keep=False)
    return df.loc[dup].copy()

def basic_stats(df):
    return {
        "num_rows": len(df),
        "start": df["timestamp"].min(),
        "end": df["timestamp"].max(),
        "num_missing_price": df[["open","high","low","close"]].isna().sum().sum(),
        "num_missing_volume": df["volume"].isna().sum(),
        "num_duplicates": df["timestamp"].duplicated().sum(),
    }

def clean_data(df):
    df = df.copy()
    df = df.dropna(subset=["timestamp"])
    df = df.drop_duplicates(subset=["timestamp"], keep="first")
    for col in ["open","high","low","close","volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open","high","low","close"])
    df["volume"] = df["volume"].fillna(0)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df
