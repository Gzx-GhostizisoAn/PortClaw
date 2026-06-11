from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, List
from uuid import uuid4

from ..schemas import (
    AssetMetrics,
    NewsEvent,
    NewsImpact,
    PortfolioMetrics,
    PortfolioSnapshot,
    RecommendedAction,
    RiskTheme,
    RiskThemeMetric,
    Severity,
    Signal,
)


SEVERITY_RANK = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


CONCENTRATION_METRIC_WEIGHTS = {
    "top_holding_weight": 0.45,
    "top_sector_weight": 0.35,
    "portfolio_hhi": 0.20,
}


@dataclass(frozen=True)
class ThemeDefinition:
    theme_key: str
    title: str
    signal_rules: set[str]
    signal_metric_names: set[str]
    base_action: RecommendedAction = RecommendedAction.REVIEW


THEME_DEFINITIONS = [
    ThemeDefinition(
        theme_key="concentration_risk",
        title="Concentration risk",
        signal_rules={"position_weight_high", "portfolio_concentration_high"},
        signal_metric_names={"position.weight", "portfolio.largest_position_weight"},
        base_action=RecommendedAction.REDUCE_OR_REVIEW,
    ),
    ThemeDefinition(
        theme_key="volatility_risk",
        title="Volatility risk",
        signal_rules={"asset_volatility_high", "portfolio_daily_loss"},
        signal_metric_names={
            "asset.volatility_20d",
            "portfolio.volatility_20d",
            "asset.max_drawdown_60d",
            "portfolio.daily_return",
        },
        base_action=RecommendedAction.WATCH,
    ),
    ThemeDefinition(
        theme_key="liquidity_risk",
        title="Liquidity risk",
        signal_rules=set(),
        signal_metric_names={"asset.liquidity_score", "asset.volume", "asset.turnover"},
        base_action=RecommendedAction.WATCH,
    ),
    ThemeDefinition(
        theme_key="macro_risk",
        title="Macro risk",
        signal_rules=set(),
        signal_metric_names={"currency.exposure", "macro.usd", "macro.rate", "macro.inflation", "macro.oil"},
        base_action=RecommendedAction.REVIEW,
    ),
    ThemeDefinition(
        theme_key="news_risk",
        title="News and event risk",
        signal_rules=set(),
        signal_metric_names={"news", "announcement", "sentiment"},
        base_action=RecommendedAction.REVIEW,
    ),
]


class RiskThemeEngine:
    """Builds ranked risk themes from signals plus portfolio and market metrics."""

    def build(
        self,
        snapshot: PortfolioSnapshot,
        asset_metrics: List[AssetMetrics],
        portfolio_metrics: PortfolioMetrics,
        signals: List[Signal],
        news_events: List[NewsEvent] | None = None,
        news_impacts: List[NewsImpact] | None = None,
        news_summary: str | None = None,
    ) -> List[RiskTheme]:
        news_events = news_events or []
        news_impacts = news_impacts or []
        signal_map = self._map_signals_to_themes(signals)
        news_impact_map = self._map_news_impacts_to_themes(news_impacts)
        asset_metric_by_symbol = {item.symbol: item for item in asset_metrics}
        themes = [
            self._build_concentration_theme(snapshot, portfolio_metrics, signal_map["concentration_risk"], news_impact_map["concentration_risk"]),
            self._build_volatility_theme(asset_metric_by_symbol, portfolio_metrics, signal_map["volatility_risk"], news_impact_map["volatility_risk"]),
            self._build_liquidity_theme(asset_metric_by_symbol, signal_map["liquidity_risk"], news_impact_map["liquidity_risk"]),
            self._build_macro_theme(portfolio_metrics, signal_map["macro_risk"], news_impact_map["macro_risk"]),
            self._build_news_theme(news_summary, signal_map["news_risk"], news_impact_map["news_risk"], news_events),
        ]

        ranked = [
            theme
            for theme in themes
            if theme.priority_score > 0
            or theme.signal_ids
            or any(metric.contribution > 0 for metric in theme.metrics)
        ]
        ranked.sort(key=lambda item: (item.priority_score, SEVERITY_RANK[item.severity]), reverse=True)
        for rank, theme in enumerate(ranked, start=1):
            theme.rank = rank
        return ranked

    def _map_signals_to_themes(self, signals: List[Signal]) -> dict[str, List[Signal]]:
        output: dict[str, List[Signal]] = defaultdict(list)
        for signal in signals:
            if signal.signal_type.value == "strategy_scan":
                continue
            metric_names = {evidence.metric_name for evidence in signal.evidence}
            matched = False
            for definition in THEME_DEFINITIONS:
                if (
                    signal.rule_id in definition.signal_rules
                    or metric_names.intersection(definition.signal_metric_names)
                ):
                    output[definition.theme_key].append(signal)
                    matched = True
            if not matched and signal.signal_type.value == "event_risk":
                output["news_risk"].append(signal)
        return output

    def _map_news_impacts_to_themes(self, impacts: List[NewsImpact]) -> dict[str, List[NewsImpact]]:
        output: dict[str, List[NewsImpact]] = defaultdict(list)
        for impact in impacts:
            output[impact.theme_key].append(impact)
        return output

    def _build_concentration_theme(
        self,
        snapshot: PortfolioSnapshot,
        portfolio_metrics: PortfolioMetrics,
        signals: List[Signal],
        news_impacts: List[NewsImpact],
    ) -> RiskTheme:
        largest = portfolio_metrics.largest_position_weight or 0.0
        hhi = portfolio_metrics.concentration_score or 0.0
        top_sector = max(
            (item for item in portfolio_metrics.exposures if item.exposure_type == "sector"),
            key=lambda item: item.weight,
            default=None,
        )
        sector_weight = top_sector.weight if top_sector else 0.0
        top_holding = max(snapshot.positions, key=lambda item: item.weight or 0.0, default=None)
        drivers = []
        if top_holding:
            drivers.append(f"Top holding {top_holding.asset.symbol} is {(top_holding.weight or 0):.1%}.")
        if top_sector:
            drivers.append(f"Top sector {top_sector.name} is {sector_weight:.1%}.")

        metrics = [
            self._metric(
                "top_holding_weight",
                largest,
                0.35,
                "portfolio_metrics",
                "Largest single-name portfolio weight.",
                weight=CONCENTRATION_METRIC_WEIGHTS["top_holding_weight"],
            ),
            self._metric(
                "top_sector_weight",
                sector_weight,
                0.50,
                "portfolio_metrics.exposures",
                "Largest sector exposure.",
                weight=CONCENTRATION_METRIC_WEIGHTS["top_sector_weight"],
            ),
            self._metric(
                "portfolio_hhi",
                hhi,
                0.25,
                "portfolio_metrics",
                "Herfindahl-Hirschman concentration index, used as a portfolio-wide diversification summary.",
                weight=CONCENTRATION_METRIC_WEIGHTS["portfolio_hhi"],
            ),
        ]
        return self._theme(
            "concentration_risk",
            "Concentration risk",
            metrics,
            signals,
            drivers,
            RecommendedAction.REDUCE_OR_REVIEW,
            news_impacts,
        )

    def _build_volatility_theme(
        self,
        asset_metrics: dict[str, AssetMetrics],
        portfolio_metrics: PortfolioMetrics,
        signals: List[Signal],
        news_impacts: List[NewsImpact],
    ) -> RiskTheme:
        vols = [item.volatility_20d for item in asset_metrics.values() if item.volatility_20d is not None]
        drawdowns = [abs(item.max_drawdown_60d) for item in asset_metrics.values() if item.max_drawdown_60d is not None]
        betas = [abs(item.beta_to_benchmark) for item in asset_metrics.values() if item.beta_to_benchmark is not None]
        avg_vol = sum(vols) / len(vols) if vols else portfolio_metrics.volatility_20d or 0.0
        worst_drawdown = max(drawdowns) if drawdowns else abs(portfolio_metrics.max_drawdown_60d or 0.0)
        avg_beta = sum(betas) / len(betas) if betas else abs(portfolio_metrics.beta_to_benchmark or 0.0)
        same_day_loss = abs(portfolio_metrics.daily_return or 0.0) if (portfolio_metrics.daily_return or 0.0) < 0 else 0.0
        drivers = self._top_metric_symbols(asset_metrics.values(), "volatility_20d", "High volatility")
        if portfolio_metrics.daily_return is not None:
            drivers.append(f"Same-day portfolio return is {portfolio_metrics.daily_return:.2%}.")
        metrics = [
            self._metric("asset_or_portfolio_volatility_20d", avg_vol, 0.04, "asset_metrics", "Average available 20-day volatility."),
            self._metric("max_drawdown_60d", worst_drawdown, 0.12, "asset_metrics", "Worst available 60-day drawdown magnitude."),
            self._metric("beta_to_benchmark", avg_beta, 1.20, "asset_metrics", "Average available beta magnitude."),
            self._metric("same_day_portfolio_loss", same_day_loss, 0.03, "portfolio_metrics.daily_return", "Magnitude of same-day portfolio loss from latest and previous close."),
        ]
        return self._theme("volatility_risk", "Volatility risk", metrics, signals, drivers, RecommendedAction.WATCH, news_impacts)

    def _build_liquidity_theme(
        self,
        asset_metrics: dict[str, AssetMetrics],
        signals: List[Signal],
        news_impacts: List[NewsImpact],
    ) -> RiskTheme:
        scores = [item.liquidity_score for item in asset_metrics.values() if item.liquidity_score is not None]
        low_score = min(scores) if scores else None
        metadata_flags = [
            f"{item.symbol}: liquidity metadata present"
            for item in asset_metrics.values()
            if any(key in item.metadata for key in ["avg_volume", "turnover", "bid_ask_spread", "market_depth"])
        ]
        metrics = []
        if low_score is not None:
            metrics.append(
                RiskThemeMetric(
                    metric_name="lowest_liquidity_score",
                    value=low_score,
                    weight=1.0,
                    contribution=self._inverse_score(low_score, 0.35),
                    source="asset_metrics",
                    explanation="Lower liquidity score indicates higher liquidation or execution risk.",
                )
            )
        return self._theme("liquidity_risk", "Liquidity risk", metrics, signals, metadata_flags, RecommendedAction.WATCH, news_impacts)

    def _build_macro_theme(
        self,
        portfolio_metrics: PortfolioMetrics,
        signals: List[Signal],
        news_impacts: List[NewsImpact],
    ) -> RiskTheme:
        currency_exposures = [item for item in portfolio_metrics.exposures if item.exposure_type == "currency"]
        non_base_weight = sum(item.weight for item in currency_exposures if item.name.upper() != "USD")
        drivers = [f"{item.name} exposure is {item.weight:.1%}." for item in currency_exposures if item.weight > 0]
        metrics = [
            self._metric("non_usd_currency_exposure", non_base_weight, 0.30, "portfolio_metrics.exposures", "Foreign-currency exposure can create macro sensitivity."),
        ]
        return self._theme("macro_risk", "Macro risk", metrics, signals, drivers, RecommendedAction.REVIEW, news_impacts)

    def _build_news_theme(
        self,
        news_summary: str | None,
        signals: List[Signal],
        news_impacts: List[NewsImpact],
        news_events: List[NewsEvent],
    ) -> RiskTheme:
        has_news = bool(news_summary and news_summary.strip())
        metrics = []
        drivers = []
        if has_news:
            drivers.append(news_summary.strip()[:240])
            metrics.append(
                RiskThemeMetric(
                    metric_name="news_summary_available",
                    value=True,
                    weight=0.5,
                    contribution=0.0,
                    source="news_summary",
                    explanation="News input exists and should be reviewed for event risk context.",
                )
            )
        drivers.extend(
            f"{event.event_type.value}: {event.title[:120]}"
            for event in sorted(news_events, key=lambda item: item.severity_score, reverse=True)[:3]
        )
        return self._theme("news_risk", "News and event risk", metrics, signals, drivers, RecommendedAction.REVIEW, news_impacts)

    def _theme(
        self,
        theme_key: str,
        title: str,
        metrics: List[RiskThemeMetric],
        signals: List[Signal],
        drivers: List[str],
        action: RecommendedAction,
        news_impacts: List[NewsImpact] | None = None,
    ) -> RiskTheme:
        news_impacts = news_impacts or []
        signal_score = self._signal_score(signals)
        news_score = self._news_impact_score(news_impacts)
        metric_score = sum(item.weight * item.contribution for item in metrics)
        priority_score = min(100.0, round((0.50 * metric_score + 0.25 * signal_score + 0.25 * news_score) * 100, 2))
        severity = self._severity_from_score(priority_score, signals)
        summary = self._summary(title, priority_score, metrics, signals, drivers, news_impacts)
        return RiskTheme(
            theme_id=f"theme_{uuid4().hex}",
            theme_key=theme_key,
            title=title,
            severity=severity,
            priority_score=priority_score,
            summary=summary,
            metrics=metrics,
            drivers=(drivers + self._news_drivers(news_impacts))[:5],
            signal_ids=[item.signal_id for item in signals],
            source_types=self._source_types(metrics, signals, news_impacts),
            recommended_action=action if priority_score >= 35 else RecommendedAction.WATCH,
            needs_human_review=priority_score >= 70 or any(item.needs_human_review for item in signals),
        )

    def _metric(
        self,
        name: str,
        value: float,
        threshold: float,
        source: str,
        explanation: str,
        weight: float = 1.0,
    ) -> RiskThemeMetric:
        contribution = min(1.0, value / threshold) if threshold > 0 else 0.0
        return RiskThemeMetric(
            metric_name=name,
            value=value,
            weight=weight,
            contribution=contribution,
            source=source,
            explanation=explanation,
        )

    def _signal_score(self, signals: Iterable[Signal]) -> float:
        scores = []
        for signal in signals:
            severity_score = SEVERITY_RANK[signal.severity] / 4
            scores.append(min(1.0, 0.65 * severity_score + 0.35 * signal.confidence))
        return max(scores) if scores else 0.0

    def _news_impact_score(self, impacts: Iterable[NewsImpact]) -> float:
        values = [impact.news_impact / 100 for impact in impacts]
        return max(values) if values else 0.0

    def _severity_from_score(self, score: float, signals: List[Signal]) -> Severity:
        signal_severity = max((signal.severity for signal in signals), key=lambda item: SEVERITY_RANK[item], default=Severity.INFO)
        metric_severity = (
            Severity.CRITICAL
            if score >= 85
            else Severity.HIGH
            if score >= 65
            else Severity.MEDIUM
            if score >= 35
            else Severity.LOW
            if score > 0
            else Severity.INFO
        )
        return max([signal_severity, metric_severity], key=lambda item: SEVERITY_RANK[item])

    def _summary(
        self,
        title: str,
        score: float,
        metrics: List[RiskThemeMetric],
        signals: List[Signal],
        drivers: List[str],
        news_impacts: List[NewsImpact],
    ) -> str:
        metric_bits = ", ".join(f"{item.metric_name}={self._format_value(item.value)}" for item in metrics[:3])
        driver_text = drivers[0] if drivers else "No dominant driver identified."
        signal_text = f"{len(signals)} mapped signal(s)" if signals else "no mapped rule signal"
        news_text = f"{len(news_impacts)} news impact(s)" if news_impacts else "no portfolio-weighted news impact"
        return f"{title} priority {score:.1f}/100 based on {metric_bits or 'available inputs'}; {signal_text}; {news_text}. {driver_text}"

    def _source_types(self, metrics: List[RiskThemeMetric], signals: List[Signal], news_impacts: List[NewsImpact]) -> List[str]:
        output = {item.source for item in metrics}
        output.update(f"signal:{item.rule_id}" for item in signals)
        output.update(f"news_impact:{item.event_id}" for item in news_impacts)
        return sorted(output)

    def _news_drivers(self, impacts: List[NewsImpact]) -> List[str]:
        return [
            f"News impact {impact.news_impact:.1f}/100: {impact.rationale}"
            for impact in sorted(impacts, key=lambda item: item.news_impact, reverse=True)[:3]
        ]

    def _inverse_score(self, value: float, threshold: float) -> float:
        if value >= threshold:
            return 0.0
        return min(1.0, (threshold - value) / threshold)

    def _top_metric_symbols(self, metrics: Iterable[AssetMetrics], attr: str, label: str) -> List[str]:
        ranked = sorted(
            ((item.symbol, getattr(item, attr)) for item in metrics if getattr(item, attr) is not None),
            key=lambda item: item[1],
            reverse=True,
        )
        return [f"{label}: {symbol} {value:.2%}" for symbol, value in ranked[:3]]

    def _format_value(self, value: object) -> str:
        if isinstance(value, float):
            return f"{value:.2%}"
        return str(value)
