from __future__ import annotations

from datetime import datetime
from typing import List
from uuid import uuid4

from ..schemas import (
    AssetMetrics,
    Evidence,
    PortfolioMetrics,
    PortfolioSnapshot,
    RecommendedAction,
    Rule,
    Severity,
    Signal,
    SignalType,
)


DEFAULT_RULES = [
    Rule(
        rule_id="position_weight_high",
        name="High single-position weight",
        signal_type=SignalType.POSITION_RISK,
        description="Flags positions whose portfolio weight exceeds the configured threshold.",
        severity=Severity.HIGH,
        thresholds={"max_weight": 0.25},
    ),
    Rule(
        rule_id="asset_volatility_high",
        name="High asset volatility",
        signal_type=SignalType.POSITION_RISK,
        description="Flags assets whose 20-day volatility is elevated.",
        severity=Severity.MEDIUM,
        thresholds={"volatility_20d": 0.04},
    ),
    Rule(
        rule_id="portfolio_concentration_high",
        name="High portfolio concentration",
        signal_type=SignalType.MARKET_RISK,
        description="Flags concentrated portfolios based on largest position weight.",
        severity=Severity.HIGH,
        thresholds={"largest_position_weight": 0.35},
    ),
    Rule(
        rule_id="trend_candidate",
        name="Trend strategy candidate",
        signal_type=SignalType.STRATEGY_SCAN,
        description="Flags assets trading above both 20-day and 60-day moving averages.",
        severity=Severity.INFO,
        thresholds={},
    ),
]


class RuleEngine:
    def __init__(self, rules: List[Rule] | None = None):
        self.rules = rules or DEFAULT_RULES

    def evaluate(
        self,
        snapshot: PortfolioSnapshot,
        asset_metrics: List[AssetMetrics],
        portfolio_metrics: PortfolioMetrics,
    ) -> List[Signal]:
        signals: List[Signal] = []
        metric_by_symbol = {item.symbol: item for item in asset_metrics}

        for rule in self.rules:
            if not rule.enabled:
                continue
            if rule.rule_id == "position_weight_high":
                signals.extend(self._position_weight_signals(rule, snapshot))
            elif rule.rule_id == "asset_volatility_high":
                signals.extend(self._asset_volatility_signals(rule, metric_by_symbol))
            elif rule.rule_id == "portfolio_concentration_high":
                signals.extend(self._portfolio_concentration_signal(rule, portfolio_metrics))
            elif rule.rule_id == "trend_candidate":
                signals.extend(self._trend_candidate_signals(rule, snapshot, metric_by_symbol))

        return signals

    def _position_weight_signals(self, rule: Rule, snapshot: PortfolioSnapshot) -> List[Signal]:
        threshold = rule.thresholds.get("max_weight", 0.25)
        output = []
        for position in snapshot.positions:
            weight = position.weight or 0.0
            if weight <= threshold:
                continue
            output.append(
                Signal(
                    signal_id=f"sig_{uuid4().hex}",
                    rule_id=rule.rule_id,
                    signal_type=rule.signal_type,
                    scope="position",
                    target=position.asset.symbol,
                    severity=rule.severity,
                    title=f"{position.asset.symbol} position weight is elevated",
                    summary=f"{position.asset.symbol} accounts for {weight:.1%} of the portfolio.",
                    evidence=[
                        Evidence(
                            metric_name="position.weight",
                            observed_value=weight,
                            threshold=threshold,
                            explanation="Single-position concentration can amplify drawdown risk.",
                        )
                    ],
                    recommended_action=RecommendedAction.REVIEW,
                    confidence=0.85,
                    needs_human_review=True,
                )
            )
        return output

    def _asset_volatility_signals(self, rule: Rule, metrics: dict[str, AssetMetrics]) -> List[Signal]:
        threshold = rule.thresholds.get("volatility_20d", 0.04)
        output = []
        for symbol, item in metrics.items():
            vol = item.volatility_20d
            if vol is None or vol <= threshold:
                continue
            output.append(
                Signal(
                    signal_id=f"sig_{uuid4().hex}",
                    rule_id=rule.rule_id,
                    signal_type=rule.signal_type,
                    scope="asset",
                    target=symbol,
                    severity=rule.severity,
                    title=f"{symbol} volatility is elevated",
                    summary=f"{symbol} has a 20-day volatility of {vol:.2%}.",
                    evidence=[
                        Evidence(
                            metric_name="asset.volatility_20d",
                            observed_value=vol,
                            threshold=threshold,
                            explanation="Elevated volatility increases position-level risk.",
                        )
                    ],
                    recommended_action=RecommendedAction.WATCH,
                    confidence=0.75,
                )
            )
        return output

    def _portfolio_concentration_signal(self, rule: Rule, metrics: PortfolioMetrics) -> List[Signal]:
        threshold = rule.thresholds.get("largest_position_weight", 0.35)
        observed = metrics.largest_position_weight or 0.0
        if observed <= threshold:
            return []
        return [
            Signal(
                signal_id=f"sig_{uuid4().hex}",
                rule_id=rule.rule_id,
                signal_type=rule.signal_type,
                scope="portfolio",
                target=metrics.portfolio_id,
                severity=rule.severity,
                title="Portfolio concentration is elevated",
                summary=f"The largest position weight is {observed:.1%}.",
                evidence=[
                    Evidence(
                        metric_name="portfolio.largest_position_weight",
                        observed_value=observed,
                        threshold=threshold,
                        explanation="Large single-position exposure can dominate portfolio outcomes.",
                    )
                ],
                recommended_action=RecommendedAction.REVIEW,
                confidence=0.85,
                needs_human_review=True,
            )
        ]

    def _trend_candidate_signals(
        self,
        rule: Rule,
        snapshot: PortfolioSnapshot,
        metrics: dict[str, AssetMetrics],
    ) -> List[Signal]:
        output = []
        held_symbols = {position.asset.symbol for position in snapshot.positions}
        for symbol, item in metrics.items():
            if symbol in held_symbols:
                continue
            latest_price = item.metadata.get("latest_price")
            ma20 = item.moving_average_20d
            ma60 = item.moving_average_60d
            if latest_price is None or ma20 is None or ma60 is None:
                continue
            if latest_price <= ma20 or latest_price <= ma60:
                continue
            output.append(
                Signal(
                    signal_id=f"sig_{uuid4().hex}",
                    rule_id=rule.rule_id,
                    signal_type=rule.signal_type,
                    scope="watchlist",
                    target=symbol,
                    severity=Severity.INFO,
                    title=f"{symbol} matches a trend scan",
                    summary=f"{symbol} is trading above its 20-day and 60-day moving averages.",
                    evidence=[
                        Evidence(
                            metric_name="price_vs_moving_average",
                            observed_value={"latest_price": latest_price, "ma20": ma20, "ma60": ma60},
                            explanation="The asset currently satisfies the simple trend candidate rule.",
                        )
                    ],
                    recommended_action=RecommendedAction.WATCH,
                    confidence=0.6,
                    created_at=datetime.utcnow(),
                )
            )
        return output
