from __future__ import annotations

from typing import Dict, Iterable

import pandas as pd

from ...config import AgentConfig
from .base import MarketDataResult
from .tushare import fetch_tushare_history
from .yahoo import fetch_yahoo_history


PLANNED_HISTORY_PROVIDERS = {
    "akshare",
    "efinance",
    "ccxt",
    "fred",
    "fmp",
    "alpha_vantage",
    "rqdata",
    "eodhd",
    "twelve_data",
}


class MarketDataClient:
    def __init__(self, config: AgentConfig):
        self.config = config

    def fetch_history(self, symbol: str, period: str = "1y") -> MarketDataResult:
        provider = self.config.market_data.provider
        if provider == "yahoo":
            return fetch_yahoo_history(symbol, period)
        if provider == "tushare":
            return fetch_tushare_history(symbol, period, self.config.market_data.api_key)
        if provider in PLANNED_HISTORY_PROVIDERS:
            return MarketDataResult(
                symbol=symbol,
                provider=provider,
                history=pd.DataFrame(),
                error=f"{provider} adapter is configured but not implemented yet",
            )
        return MarketDataResult(
            symbol=symbol,
            provider=provider,
            history=pd.DataFrame(),
            error="demo provider uses local portfolio prices",
        )

    def fetch_many(self, symbols: Iterable[str], period: str = "1y") -> Dict[str, MarketDataResult]:
        return {symbol: self.fetch_history(symbol, period) for symbol in sorted(set(symbols))}
