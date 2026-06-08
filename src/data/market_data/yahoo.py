from __future__ import annotations

import pandas as pd

from .base import MarketDataResult
from .metrics import normalize_history


def fetch_yahoo_history(symbol: str, period: str) -> MarketDataResult:
    try:
        import yfinance as yf
    except ImportError:
        return MarketDataResult(
            symbol=symbol,
            provider="yahoo",
            history=pd.DataFrame(),
            error="yfinance is not installed",
        )

    try:
        df = yf.download(symbol, period=period, interval="1d", auto_adjust=False, progress=False)
        normalized = normalize_history(df)
        if normalized.empty:
            return MarketDataResult(symbol=symbol, provider="yahoo", history=normalized, error="empty history")
        return MarketDataResult(symbol=symbol, provider="yahoo", history=normalized)
    except Exception as exc:
        return MarketDataResult(symbol=symbol, provider="yahoo", history=pd.DataFrame(), error=str(exc))
