import pandas as pd
import yfinance as yf

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

    # Ensure we always work with an explicit timestamp column
    data.index = pd.to_datetime(data.index, errors="coerce")
    data.index.name = "timestamp"
    data = data.reset_index()
    data["timestamp"] = pd.to_datetime(data["timestamp"], errors="coerce")
    data = data.dropna(subset=["timestamp"])

    numeric_cols = [col for col in ["open", "high", "low", "close", "volume"] if col in data.columns]
    for col in numeric_cols:
        data[col] = pd.to_numeric(data[col], errors="coerce")

    # Remove rows where OHLC values could not be converted
    data = data.dropna(subset=[col for col in ["open", "high", "low", "close"] if col in data.columns])

    if "volume" not in data.columns:
        data["volume"] = 0.0
    else:
        data["volume"] = data["volume"].fillna(0)

    if data.empty:
        raise ValueError("Dati non validi dopo la pulizia")

    if timeframe == "4h":
        data = resample_ohlcv(data, timeframe)

    data = data.sort_values("timestamp").reset_index(drop=True)

    return data[["timestamp", "open", "high", "low", "close", "volume"]]

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
