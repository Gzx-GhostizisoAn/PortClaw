from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class MarketDataResult:
    symbol: str
    provider: str
    history: pd.DataFrame
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and not self.history.empty
