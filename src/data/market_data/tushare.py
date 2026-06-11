from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from .base import MarketDataResult
from .metrics import normalize_history


def fetch_tushare_history(symbol: str, period: str, token: str) -> MarketDataResult:
    if not token:
        return MarketDataResult(
            symbol=symbol,
            provider="tushare",
            history=pd.DataFrame(),
            error="Tushare token is required",
        )

    try:
        import tushare as ts
    except ImportError:
        return MarketDataResult(
            symbol=symbol,
            provider="tushare",
            history=pd.DataFrame(),
            error="tushare is not installed",
        )

    ts_code = normalize_tushare_symbol(symbol)
    if not ts_code:
        return MarketDataResult(
            symbol=symbol,
            provider="tushare",
            history=pd.DataFrame(),
            error="Tushare supports China-market ts_code symbols such as 600519.SH or 000001.SZ",
        )

    start_date, end_date = _period_to_dates(period)
    try:
        pro = ts.pro_api(token)
        raw = pro.daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields="ts_code,trade_date,open,high,low,close,vol,amount",
        )
        normalized = _normalize_tushare_daily(raw)
        if normalized.empty:
            return MarketDataResult(symbol=symbol, provider="tushare", history=normalized, error="empty history")
        return MarketDataResult(symbol=symbol, provider="tushare", history=normalized)
    except Exception as exc:
        return MarketDataResult(symbol=symbol, provider="tushare", history=pd.DataFrame(), error=str(exc))


def normalize_tushare_symbol(symbol: str) -> str | None:
    cleaned = symbol.strip().upper()
    if not cleaned:
        return None
    if "." in cleaned:
        code, exchange = cleaned.rsplit(".", 1)
        if code.isdigit() and len(code) == 6 and exchange in {"SH", "SZ", "BJ"}:
            return f"{code}.{exchange}"
        return None
    if not (cleaned.isdigit() and len(cleaned) == 6):
        return None
    if cleaned.startswith(("5", "6", "9")):
        return f"{cleaned}.SH"
    if cleaned.startswith(("0", "1", "2", "3")):
        return f"{cleaned}.SZ"
    if cleaned.startswith(("4", "8")):
        return f"{cleaned}.BJ"
    return None


def _normalize_tushare_daily(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    output = df.rename(
        columns={
            "trade_date": "Date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "vol": "Volume",
        }
    )
    if "Date" in output.columns:
        output = output.set_index("Date")
    return normalize_history(output)


def _period_to_dates(period: str) -> tuple[str, str]:
    today = datetime.utcnow().date()
    period_key = period.strip().lower()
    days_by_period = {
        "1d": 1,
        "5d": 5,
        "1mo": 31,
        "3mo": 93,
        "6mo": 186,
        "1y": 366,
        "2y": 366 * 2,
        "5y": 366 * 5,
        "10y": 366 * 10,
    }
    if period_key == "ytd":
        start = today.replace(month=1, day=1)
    elif period_key in {"max", "all"}:
        start = today.replace(year=1990, month=1, day=1)
    else:
        start = today - timedelta(days=days_by_period.get(period_key, 366))
    return start.strftime("%Y%m%d"), today.strftime("%Y%m%d")
