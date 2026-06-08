from __future__ import annotations

from typing import Dict, Iterable

import pandas as pd

from ...config import AgentConfig
from .base import MarketDataResult
from .yahoo import fetch_yahoo_history


class MarketDataClient:
    def __init__(self, config: AgentConfig):
        self.config = config

    def fetch_history(self, symbol: str, period: str = "1y") -> MarketDataResult:
        provider = self.config.market_data.provider
        if provider == "yahoo":
            return fetch_yahoo_history(symbol, period)
        if provider in {"akshare", "eodhd", "twelve_data"}:
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
