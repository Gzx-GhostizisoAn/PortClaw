from __future__ import annotations

from datetime import datetime
from typing import List
from uuid import uuid4

from .analytics.metrics import calculate_portfolio_metrics
from .analytics.signals import RuleEngine
from .intelligence import RiskThemeEngine
from .schemas import (
    AssetMetrics,
    DailyBrief,
    NewsEvent,
    NewsImpact,
    NewsItem,
    PortfolioSnapshot,
    SignalType,
)


class DailyPipeline:
    """Coordinates the daily analysis flow over already-normalized objects."""

    def __init__(self, rule_engine: RuleEngine | None = None, risk_theme_engine: RiskThemeEngine | None = None):
        self.rule_engine = rule_engine or RuleEngine()
        self.risk_theme_engine = risk_theme_engine or RiskThemeEngine()

    def run(
        self,
        snapshot: PortfolioSnapshot,
        asset_metrics: List[AssetMetrics],
        news_items: List[NewsItem] | None = None,
        news_events: List[NewsEvent] | None = None,
        news_impacts: List[NewsImpact] | None = None,
        news_summary: str | None = None,
    ) -> DailyBrief:
        news_items = news_items or []
        news_events = news_events or []
        news_impacts = news_impacts or []
        portfolio_metrics = calculate_portfolio_metrics(snapshot)
        signals = self.rule_engine.evaluate(snapshot, asset_metrics, portfolio_metrics)
        risk_themes = self.risk_theme_engine.build(
            snapshot=snapshot,
            asset_metrics=asset_metrics,
            portfolio_metrics=portfolio_metrics,
            signals=signals,
            news_events=news_events,
            news_impacts=news_impacts,
            news_summary=news_summary,
        )
        strategy_candidates = [signal for signal in signals if signal.signal_type == SignalType.STRATEGY_SCAN]
        human_review_items = [
            f"Theme #{theme.rank}: {theme.title} ({theme.priority_score:.1f}/100)"
            for theme in risk_themes
            if theme.needs_human_review
        ]
        human_review_items.extend(
            f"{signal.target}: {signal.title}"
            for signal in signals
            if signal.needs_human_review
        )

        return DailyBrief(
            brief_id=f"brief_{uuid4().hex}",
            as_of=datetime.utcnow(),
            portfolio_snapshot=snapshot,
            portfolio_metrics=portfolio_metrics,
            asset_metrics=asset_metrics,
            signals=signals,
            risk_themes=risk_themes,
            strategy_candidates=strategy_candidates,
            news_items=news_items,
            news_events=news_events,
            news_impacts=news_impacts,
            news_summary=news_summary,
            human_review_items=human_review_items,
        )
