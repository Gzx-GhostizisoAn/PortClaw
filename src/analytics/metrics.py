from __future__ import annotations

from typing import List

from ..schemas import Exposure, PortfolioMetrics, PortfolioSnapshot
from .exposures import basic_stress_tests, calculate_exposures


def calculate_portfolio_metrics(snapshot: PortfolioSnapshot) -> PortfolioMetrics:
    weights = [position.weight or 0.0 for position in snapshot.positions]
    largest_weight = max(weights) if weights else 0.0
    exposures = calculate_exposures(snapshot)

    return PortfolioMetrics(
        portfolio_id=snapshot.snapshot_id,
        as_of=snapshot.as_of,
        total_return=safe_total_return(snapshot),
        daily_return=safe_daily_return(snapshot),
        largest_position_weight=largest_weight,
        concentration_score=sum(weight * weight for weight in weights),
        sector_concentration_score=sector_concentration_score(exposures),
        exposures=exposures,
        stress_tests=basic_stress_tests(snapshot),
    )


def safe_total_return(snapshot: PortfolioSnapshot) -> float | None:
    if snapshot.total_cost <= 0:
        return None
    return (snapshot.total_market_value - snapshot.total_cost) / snapshot.total_cost


def safe_daily_return(snapshot: PortfolioSnapshot) -> float | None:
    daily_pnl = 0.0
    previous_total = snapshot.cash
    has_daily_data = False
    for position in snapshot.positions:
        if position.daily_pnl is None or position.previous_close is None:
            continue
        daily_pnl += position.daily_pnl
        previous_total += position.quantity * position.previous_close
        has_daily_data = True
    if not has_daily_data or previous_total <= 0:
        return None
    return daily_pnl / previous_total


def sector_concentration_score(exposures: List[Exposure]) -> float:
    sector_weights = [item.weight for item in exposures if item.exposure_type == "sector"]
    return sum(weight * weight for weight in sector_weights)
