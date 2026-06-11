from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import AgentConfig
from ..data.market_data import MarketDataClient, calculate_asset_metrics
from ..portfolio_input import default_portfolio_path
from ..schemas import Asset, AssetMetrics, PortfolioSnapshot, Position


def load_portfolio_snapshot(
    config: AgentConfig,
    path: Path | None = None,
) -> tuple[PortfolioSnapshot, list[AssetMetrics]]:
    path = path or default_portfolio_path()
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    market_client = MarketDataClient(config)
    position_symbols = [str(item["symbol"]).strip().upper() for item in data.get("positions", [])]
    watchlist_symbols = [str(item["symbol"]).strip().upper() for item in data.get("watchlist", [])]
    histories = market_client.fetch_many(position_symbols + watchlist_symbols)
    positions = []
    total_market_value = float(data.get("cash", 0.0))
    total_cost = 0.0

    for item in data.get("positions", []):
        symbol = str(item["symbol"]).strip().upper()
        quantity = float(item["quantity"])
        average_cost = float(item["average_cost"])
        history_result = histories.get(symbol)
        history_price = _latest_history_price(history_result)
        previous_close = _previous_history_close(history_result)
        market_data_ok = bool(history_result and history_result.ok)
        market_price = history_price if history_price is not None else float(item["market_price"])
        market_value = quantity * market_price
        cost = quantity * average_cost
        daily_pnl = quantity * (market_price - previous_close) if previous_close is not None else None
        previous_value = quantity * previous_close if previous_close is not None else None
        total_market_value += market_value
        total_cost += cost
        positions.append(
            Position(
                asset=Asset(
                    symbol=symbol,
                    name=item.get("name"),
                    sector=item.get("sector"),
                    currency=data.get("base_currency", config.base_currency),
                    metadata={
                        "market_data_provider": history_result.provider if history_result else config.market_data.provider,
                        "market_data_error": history_result.error if history_result else None,
                        "field_sources": {
                            "market_price": "provider_history" if history_price is not None else "portfolio_file_fallback",
                            "previous_close": "provider_history" if previous_close is not None else "unavailable",
                            "daily_pnl": "provider_history" if previous_close is not None else "unavailable",
                            "market_value": "provider_history" if market_data_ok else "portfolio_file_fallback",
                            "unrealized_pnl": "provider_history" if market_data_ok else "portfolio_file_fallback",
                        },
                    },
                ),
                quantity=quantity,
                average_cost=average_cost,
                market_price=market_price,
                previous_close=previous_close,
                market_value=market_value,
                daily_pnl=daily_pnl,
                daily_pnl_pct=daily_pnl / previous_value if previous_value else None,
                unrealized_pnl=market_value - cost,
                unrealized_pnl_pct=(market_value - cost) / cost if cost else None,
            )
        )

    for position in positions:
        position.weight = (position.market_value or 0.0) / total_market_value if total_market_value else 0.0

    snapshot = PortfolioSnapshot(
        snapshot_id=f"snapshot_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
        user_id=data.get("user_id", config.user_id),
        as_of=datetime.utcnow(),
        base_currency=data.get("base_currency", config.base_currency),
        positions=positions,
        cash=float(data.get("cash", 0.0)),
        total_market_value=total_market_value,
        total_cost=total_cost,
        metadata={
            "source": str(path),
            "market_data_provider": config.market_data.provider,
            "requested_symbols": position_symbols + watchlist_symbols,
        },
    )

    asset_metrics = []
    for position in positions:
        history_result = histories.get(position.asset.symbol)
        if history_result and history_result.ok:
            metric = calculate_asset_metrics(
                position.asset.symbol,
                history_result.history,
                cost_basis_return=position.unrealized_pnl_pct,
            )
        else:
            metric = _fallback_position_metrics(position, history_result.error if history_result else None)
        asset_metrics.append(metric)

    for item in data.get("watchlist", []):
        symbol = str(item["symbol"]).strip().upper()
        history_result = histories.get(symbol)
        if history_result and history_result.ok:
            metric = calculate_asset_metrics(symbol, history_result.history)
        else:
            metric = AssetMetrics(
                symbol=symbol,
                as_of=snapshot.as_of,
                volatility_20d=_optional_float(item.get("volatility_20d")),
                moving_average_20d=_optional_float(item.get("moving_average_20d")),
                moving_average_60d=_optional_float(item.get("moving_average_60d")),
                metadata={
                    "latest_price": _optional_float(item.get("latest_price")),
                    "metric_source": "portfolio_file",
                    "market_data_error": history_result.error if history_result else None,
                },
            )
        asset_metrics.append(metric)

    return snapshot, asset_metrics


def _latest_history_price(history_result) -> float | None:
    if not history_result or not history_result.ok:
        return None
    return float(history_result.history["close"].iloc[-1])


def _previous_history_close(history_result) -> float | None:
    if not history_result or not history_result.ok or len(history_result.history) < 2:
        return None
    return float(history_result.history["close"].iloc[-2])


def _fallback_position_metrics(position: Position, error: str | None) -> AssetMetrics:
    price = position.market_price or 0.0
    return AssetMetrics(
        symbol=position.asset.symbol,
        as_of=datetime.utcnow(),
        cumulative_return=position.unrealized_pnl_pct,
        moving_average_20d=price * 0.98 if price else None,
        moving_average_60d=price * 0.94 if price else None,
        metadata={
            "latest_price": position.market_price,
            "metric_source": "portfolio_file_fallback",
            "market_data_error": error,
        },
    )


def _optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)
