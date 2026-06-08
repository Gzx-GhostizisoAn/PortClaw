from __future__ import annotations

from collections import defaultdict
from typing import List

from ..schemas import Exposure, PortfolioSnapshot, StressTestResult


def calculate_exposures(snapshot: PortfolioSnapshot) -> List[Exposure]:
    sector_weights: dict[str, float] = defaultdict(float)
    currency_weights: dict[str, float] = defaultdict(float)
    sector_symbols: dict[str, List[str]] = defaultdict(list)
    currency_symbols: dict[str, List[str]] = defaultdict(list)

    for position in snapshot.positions:
        weight = position.weight or 0.0
        sector = position.asset.sector or "unknown"
        currency = position.asset.currency or snapshot.base_currency
        sector_weights[sector] += weight
        currency_weights[currency] += weight
        sector_symbols[sector].append(position.asset.symbol)
        currency_symbols[currency].append(position.asset.symbol)

    exposures = [
        Exposure(exposure_type="sector", name=name, weight=weight, symbols=sector_symbols[name])
        for name, weight in sector_weights.items()
    ]
    exposures.extend(
        Exposure(exposure_type="currency", name=name, weight=weight, symbols=currency_symbols[name])
        for name, weight in currency_weights.items()
    )
    return exposures


def basic_stress_tests(snapshot: PortfolioSnapshot) -> List[StressTestResult]:
    return [
        StressTestResult(
            scenario_id="market_down_5pct",
            title="Broad market down 5%",
            estimated_portfolio_change=-0.05 * snapshot.total_market_value,
            affected_symbols=[position.asset.symbol for position in snapshot.positions],
            assumptions={"shock": -0.05, "correlation": "all_positions"},
        )
    ]

