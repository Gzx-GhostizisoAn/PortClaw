from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd


def normalize_history(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    output = df.copy()
    if isinstance(output.columns, pd.MultiIndex):
        output.columns = [col[0] if isinstance(col, tuple) else col for col in output.columns]
    output = output.reset_index()
    rename_map = {
        "Date": "date",
        "Datetime": "date",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Adj Close": "adjusted_close",
        "Volume": "volume",
    }
    output = output.rename(columns=rename_map)
    required = ["date", "open", "high", "low", "close", "volume"]
    if any(col not in output.columns for col in required):
        return pd.DataFrame()
    output["date"] = pd.to_datetime(output["date"], errors="coerce")
    for col in ["open", "high", "low", "close", "volume", "adjusted_close"]:
        if col in output.columns:
            output[col] = pd.to_numeric(output[col], errors="coerce")
    return output.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)


def calculate_asset_metrics(symbol: str, history: pd.DataFrame, cost_basis_return: float | None = None):
    from ...schemas import AssetMetrics

    if history.empty or "close" not in history.columns:
        return AssetMetrics(symbol=symbol, as_of=datetime.utcnow(), cumulative_return=cost_basis_return)

    close = history["close"].astype(float)
    returns = close.pct_change().dropna()
    latest_price = float(close.iloc[-1])
    daily_return = float(returns.iloc[-1]) if not returns.empty else None
    volatility_20d = float(returns.tail(20).std()) if len(returns) >= 2 else None
    ma20 = float(close.tail(20).mean()) if len(close) >= 20 else None
    ma60 = float(close.tail(60).mean()) if len(close) >= 60 else None
    max_drawdown_60d = _max_drawdown(close.tail(60)) if len(close) >= 2 else None
    rsi_14 = _rsi(close, 14)

    return AssetMetrics(
        symbol=symbol,
        as_of=datetime.utcnow(),
        daily_return=daily_return,
        cumulative_return=cost_basis_return,
        volatility_20d=volatility_20d,
        max_drawdown_60d=max_drawdown_60d,
        rsi_14=rsi_14,
        moving_average_20d=ma20,
        moving_average_60d=ma60,
        metadata={
            "latest_price": latest_price,
            "history_points": int(len(history)),
            "metric_source": "market_history",
        },
    )


def _max_drawdown(close: pd.Series) -> float | None:
    if close.empty:
        return None
    running_max = close.cummax()
    drawdown = close / running_max.replace(0, np.nan) - 1
    return float(drawdown.min())


def _rsi(close: pd.Series, window: int) -> float | None:
    if len(close) < window + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window).mean()
    loss = (-delta.clip(upper=0)).rolling(window).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    latest = rsi.dropna()
    return float(latest.iloc[-1]) if not latest.empty else None
