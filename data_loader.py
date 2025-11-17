import pandas as pd
import yfinance as yf
from datetime import datetime

_YF_INTERVAL_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "60m",
    "4h": "60m",
    "1d": "1d",
}

_RESAMPLE_RULES = {
    "1m": "1T",
    "5m": "5T",
    "15m": "15T",
    "1h": "1H",
    "4h": "4H",
    "1d": "1D",
}

def _normalize_symbol(market_type: str, symbol: str) -> str:
    market_type = market_type.lower()
    if market_type == "forex":
        if not symbol.endswith("=X"):
            return symbol.upper() + "=X"
        return symbol.upper()
    if market_type == "crypto":
        symbol = symbol.upper()
        if symbol.endswith("USDT"):
            base = symbol.replace("USDT", "")
            return base + "-USDT"
        if symbol.endswith("USD"):
            base = symbol.replace("USD", "")
            return base + "-USD"
        return symbol + "-USD"
    return symbol.upper()

def download_data(market_type, symbol, timeframe, start_date, end_date):
    yf_symbol = _normalize_symbol(market_type, symbol)
    interval = _YF_INTERVAL_MAP[timeframe]

    data = yf.download(
        yf_symbol,
        start=start_date,
        end=end_date,
        interval=interval,
        auto_adjust=False,
        progress=False,
    )

    if data.empty:
        raise ValueError(f"Nessun dato per {yf_symbol}")

    data = data.rename(columns={
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Adj Close": "adj_close",
        "Volume": "volume",
    })

    data.index.name = "timestamp"
    data.reset_index(inplace=True)

    if timeframe == "4h":
        data = resample_ohlcv(data, timeframe)

    return data[["timestamp","open","high","low","close","volume"]]

def resample_ohlcv(df, timeframe):
    rule = _RESAMPLE_RULES[timeframe]
    df = df.copy()
    df.set_index("timestamp", inplace=True)
    ohlc = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    r = df.resample(rule).agg(ohlc).dropna()
    r.reset_index(inplace=True)
    return r
