from __future__ import annotations

from datetime import datetime
from typing import Iterable, List
from uuid import uuid4

from ..config import AgentConfig
from ..schemas import (
    NewsEvent,
    NewsEventCategory,
    NewsEventType,
    NewsImpact,
    NewsItem,
    PortfolioSnapshot,
)


EVENT_RULES = [
    {
        "event_type": NewsEventType.MACRO_RATES,
        "category": NewsEventCategory.MACRO,
        "keywords": {"fed", "federal reserve", "rate", "rates", "yield", "treasury", "central bank"},
        "theme_keys": ["macro_risk", "volatility_risk"],
    },
    {
        "event_type": NewsEventType.MACRO_INFLATION,
        "category": NewsEventCategory.MACRO,
        "keywords": {"inflation", "cpi", "ppi", "prices", "deflation"},
        "theme_keys": ["macro_risk", "volatility_risk"],
    },
    {
        "event_type": NewsEventType.MACRO_USD,
        "category": NewsEventCategory.MACRO,
        "keywords": {"dollar", "usd", "currency", "fx"},
        "theme_keys": ["macro_risk"],
    },
    {
        "event_type": NewsEventType.MACRO_OIL,
        "category": NewsEventCategory.MACRO,
        "keywords": {"oil", "crude", "opec", "energy prices"},
        "theme_keys": ["macro_risk", "volatility_risk"],
    },
    {
        "event_type": NewsEventType.INDUSTRY_POLICY,
        "category": NewsEventCategory.INDUSTRY,
        "keywords": {"export control", "restriction", "sanction", "tariff", "regulation", "policy", "ban"},
        "theme_keys": ["news_risk", "macro_risk"],
    },
    {
        "event_type": NewsEventType.INDUSTRY_DEMAND,
        "category": NewsEventCategory.INDUSTRY,
        "keywords": {"demand", "orders", "shipment", "inventory", "cycle"},
        "theme_keys": ["news_risk", "volatility_risk"],
    },
    {
        "event_type": NewsEventType.INDUSTRY_SUPPLY_CHAIN,
        "category": NewsEventCategory.INDUSTRY,
        "keywords": {"supply chain", "shortage", "capacity", "foundry", "fab", "supplier"},
        "theme_keys": ["news_risk", "volatility_risk"],
    },
    {
        "event_type": NewsEventType.COMPANY_EARNINGS,
        "category": NewsEventCategory.COMPANY,
        "keywords": {"earnings", "revenue", "profit", "margin", "eps", "results"},
        "theme_keys": ["news_risk", "volatility_risk"],
    },
    {
        "event_type": NewsEventType.COMPANY_GUIDANCE,
        "category": NewsEventCategory.COMPANY,
        "keywords": {"guidance", "forecast", "outlook", "warning", "cut"},
        "theme_keys": ["news_risk", "volatility_risk"],
    },
    {
        "event_type": NewsEventType.COMPANY_REGULATORY,
        "category": NewsEventCategory.COMPANY,
        "keywords": {"sec", "probe", "investigation", "lawsuit", "antitrust", "recall"},
        "theme_keys": ["news_risk", "liquidity_risk"],
    },
    {
        "event_type": NewsEventType.COMPANY_PRODUCT,
        "category": NewsEventCategory.COMPANY,
        "keywords": {"launch", "product", "chip", "ai", "gpu", "platform", "approval"},
        "theme_keys": ["news_risk", "volatility_risk"],
    },
    {
        "event_type": NewsEventType.COMPANY_SENTIMENT,
        "category": NewsEventCategory.COMPANY,
        "keywords": {
            "bearish",
            "concern",
            "controversy",
            "downgrade",
            "fraud",
            "negative",
            "plunge",
            "sell-off",
            "slump",
            "weak demand",
        },
        "theme_keys": ["news_risk", "volatility_risk"],
    },
]


HIGH_SEVERITY_KEYWORDS = {
    "ban",
    "blocked",
    "restriction",
    "sanction",
    "probe",
    "investigation",
    "lawsuit",
    "default",
    "bankruptcy",
    "miss",
    "cut",
    "warning",
    "fraud",
    "plunge",
    "sell-off",
}

MEDIUM_SEVERITY_KEYWORDS = {
    "tariff",
    "regulation",
    "recall",
    "shortage",
    "downgrade",
    "delay",
    "weak",
    "slows",
    "concern",
    "controversy",
}

SECTOR_KEYWORDS = {
    "Technology": {"ai", "chip", "semiconductor", "software", "cloud", "gpu", "foundry", "export control"},
    "Financials": {"bank", "insurance", "credit", "loan", "deposit", "capital ratio"},
    "Energy": {"oil", "gas", "crude", "opec", "refinery"},
    "Healthcare": {"drug", "fda", "clinical", "biotech", "medicare"},
    "Consumer": {"retail", "consumer", "spending", "inventory"},
}


class NewsFetcher:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.last_status: dict[str, object] = {
            "component": "news",
            "provider": config.market_data.provider,
            "status": "not_requested",
            "errors": [],
        }

    def fetch(self, symbols: Iterable[str], limit_per_symbol: int = 5) -> List[NewsItem]:
        provider = self.config.market_data.provider
        self.last_status = {
            "component": "news",
            "provider": provider,
            "status": "not_requested",
            "errors": [],
        }
        if provider == "yahoo":
            items = self._fetch_yfinance_news(symbols, limit_per_symbol)
            if items:
                self.last_status.update({"status": "ok", "item_count": len(items)})
            elif not self.last_status.get("errors"):
                self.last_status.update({"status": "empty", "item_count": 0})
            return items
        if provider in {
            "sec",
            "akshare",
            "efinance",
            "ccxt",
            "fred",
            "fmp",
            "tushare",
            "alpha_vantage",
            "rqdata",
            "eodhd",
            "twelve_data",
        }:
            self.last_status.update(
                {
                    "status": "not_implemented",
                    "errors": [f"{provider} news adapter is not implemented yet"],
                    "item_count": 0,
                }
            )
            return []
        self.last_status.update(
            {
                "status": "not_available",
                "errors": [f"{provider} does not provide a configured news adapter"],
                "item_count": 0,
            }
        )
        return []

    def _fetch_yfinance_news(self, symbols: Iterable[str], limit_per_symbol: int) -> List[NewsItem]:
        try:
            import yfinance as yf
        except ImportError:
            self.last_status.update({"status": "error", "errors": ["yfinance is not installed"], "item_count": 0})
            return []

        output: list[NewsItem] = []
        seen: set[tuple[str, str | None]] = set()
        errors: list[str] = []
        for symbol in sorted(set(symbols)):
            try:
                raw_items = yf.Ticker(symbol).news or []
            except Exception as exc:
                errors.append(f"{symbol}: {exc}")
                continue
            for raw in raw_items[:limit_per_symbol]:
                item = self._normalize_yfinance_item(raw, symbol)
                key = (item.title, item.url)
                if key in seen:
                    continue
                seen.add(key)
                output.append(item)
        if errors:
            self.last_status.update({"status": "partial" if output else "error", "errors": errors, "item_count": len(output)})
        return output

    def _normalize_yfinance_item(self, raw: dict, symbol: str) -> NewsItem:
        content_payload = raw.get("content") if isinstance(raw.get("content"), dict) else {}
        content = raw.get("summary") or content_payload.get("summary") or content_payload.get("description") or ""
        title = raw.get("title") or content_payload.get("title") or ""
        timestamp = raw.get("providerPublishTime") or raw.get("pubDate")
        if isinstance(timestamp, (int, float)):
            published_at = datetime.utcfromtimestamp(timestamp)
        else:
            published_at = datetime.utcnow()
        return NewsItem(
            title=str(title),
            content=str(content),
            source=str(raw.get("publisher") or raw.get("source") or "yfinance"),
            timestamp=published_at,
            symbols=[symbol],
            url=raw.get("link") or raw.get("url") or content_payload.get("canonicalUrl", {}).get("url"),
            metadata={"provider": "yfinance"},
        )


class NewsEventClassifier:
    def classify(self, items: List[NewsItem]) -> List[NewsEvent]:
        events: list[NewsEvent] = []
        for index, item in enumerate(items):
            text = self._text(item)
            matched = False
            for rule in EVENT_RULES:
                keywords = sorted(keyword for keyword in rule["keywords"] if keyword in text)
                if not keywords:
                    continue
                events.append(
                    NewsEvent(
                        event_id=f"event_{uuid4().hex}",
                        event_type=rule["event_type"],
                        category=rule["category"],
                        title=item.title,
                        summary=(item.content or item.title)[:500],
                        severity_score=self._severity(text),
                        theme_keys=list(rule["theme_keys"]),
                        symbols=item.symbols,
                        keywords=keywords,
                        source_news_index=index,
                    )
                )
                matched = True
            if not matched:
                events.append(
                    NewsEvent(
                        event_id=f"event_{uuid4().hex}",
                        event_type=NewsEventType.UNKNOWN,
                        category=NewsEventCategory.UNKNOWN,
                        title=item.title,
                        summary=(item.content or item.title)[:500],
                        severity_score=0.25,
                        theme_keys=["news_risk"],
                        symbols=item.symbols,
                        source_news_index=index,
                    )
                )
        return events

    def _severity(self, text: str) -> float:
        if any(keyword in text for keyword in HIGH_SEVERITY_KEYWORDS):
            return 0.90
        if any(keyword in text for keyword in MEDIUM_SEVERITY_KEYWORDS):
            return 0.65
        return 0.40

    def _text(self, item: NewsItem) -> str:
        return f"{item.title} {item.content}".lower()


class NewsImpactAnalyzer:
    def analyze(self, snapshot: PortfolioSnapshot, events: List[NewsEvent]) -> List[NewsImpact]:
        impacts: list[NewsImpact] = []
        event_cluster_counts = self._event_cluster_counts(events)
        for event in events:
            exposure, affected_symbols, rationale = self._portfolio_exposure(snapshot, event)
            relevance = 1.0 if affected_symbols else 0.25 if event.category == NewsEventCategory.MACRO else 0.0
            cluster_count = self._cluster_count(event, event_cluster_counts)
            base_impact = round(event.severity_score * exposure * relevance * 100, 2)
            amplification_factor, amplification_reasons = self._amplification(event, exposure, cluster_count)
            news_impact = round(min(100.0, base_impact * amplification_factor), 2)
            for theme_key in event.theme_keys:
                impacts.append(
                    NewsImpact(
                        impact_id=f"impact_{uuid4().hex}",
                        event_id=event.event_id,
                        theme_key=theme_key,
                        event_severity=event.severity_score,
                        portfolio_exposure=exposure,
                        relevance_score=relevance,
                        base_impact=base_impact,
                        amplification_factor=amplification_factor,
                        news_impact=news_impact,
                        affected_symbols=affected_symbols,
                        rationale=self._impact_rationale(rationale, amplification_reasons),
                        metadata={
                            "cluster_count": cluster_count,
                            "amplification_reasons": amplification_reasons,
                        },
                    )
                )
        return impacts

    def _event_cluster_counts(self, events: List[NewsEvent]) -> dict[tuple[str, str], int]:
        counts: dict[tuple[str, str], int] = {}
        for event in events:
            symbol_key = ",".join(sorted(symbol.upper() for symbol in event.symbols)) or "macro_or_unknown"
            key = (event.event_type.value, symbol_key)
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _cluster_count(self, event: NewsEvent, counts: dict[tuple[str, str], int]) -> int:
        symbol_key = ",".join(sorted(symbol.upper() for symbol in event.symbols)) or "macro_or_unknown"
        return counts.get((event.event_type.value, symbol_key), 1)

    def _amplification(self, event: NewsEvent, exposure: float, cluster_count: int) -> tuple[float, list[str]]:
        factor = 1.0
        reasons: list[str] = []
        severity_boost = round((event.severity_score**2) * 0.60, 3)
        if severity_boost:
            factor += severity_boost
            reasons.append(f"severity convexity +{severity_boost:.2f}")
        exposure_boost = round((exposure**2) * 0.50, 3)
        if exposure_boost:
            factor += exposure_boost
            reasons.append(f"portfolio exposure convexity +{exposure_boost:.2f}")
        if cluster_count > 1:
            cluster_boost = min(0.75, (cluster_count - 1) * 0.25)
            factor += cluster_boost
            reasons.append(f"similar event cluster +{cluster_boost:.2f}")
        if event.event_type == NewsEventType.COMPANY_SENTIMENT:
            factor += 0.30
            reasons.append("negative sentiment event +0.30")
        capped = min(2.5, factor)
        if capped < factor:
            reasons.append("amplification capped at 2.50")
        return round(capped, 2), reasons

    def _impact_rationale(self, base_rationale: str, amplification_reasons: list[str]) -> str:
        if not amplification_reasons:
            return base_rationale
        return f"{base_rationale} Nonlinear amplification: {', '.join(amplification_reasons)}."

    def _portfolio_exposure(self, snapshot: PortfolioSnapshot, event: NewsEvent) -> tuple[float, list[str], str]:
        symbol_set = {symbol.upper() for symbol in event.symbols}
        direct = [
            position
            for position in snapshot.positions
            if position.asset.symbol.upper() in symbol_set
        ]
        if direct:
            exposure = sum(position.weight or 0.0 for position in direct)
            return exposure, [position.asset.symbol for position in direct], "Direct symbol overlap with portfolio holdings."

        if event.category == NewsEventCategory.INDUSTRY:
            sectors = self._matched_sectors(event)
            sector_positions = [
                position
                for position in snapshot.positions
                if position.asset.sector in sectors
            ]
            if sector_positions:
                exposure = sum(position.weight or 0.0 for position in sector_positions)
                return exposure, [position.asset.symbol for position in sector_positions], f"Industry event matched sectors: {', '.join(sorted(sectors))}."

        if event.category == NewsEventCategory.MACRO:
            invested_weight = sum(position.weight or 0.0 for position in snapshot.positions)
            symbols = [position.asset.symbol for position in snapshot.positions]
            return min(1.0, invested_weight), symbols, "Macro event is applied to invested portfolio exposure."

        return 0.0, [], "No direct symbol, sector, or macro exposure match."

    def _matched_sectors(self, event: NewsEvent) -> set[str]:
        text = f"{event.title} {event.summary} {' '.join(event.keywords)}".lower()
        return {
            sector
            for sector, keywords in SECTOR_KEYWORDS.items()
            if any(keyword in text for keyword in keywords)
        }


class NewsLayer:
    def __init__(self, config: AgentConfig):
        self.fetcher = NewsFetcher(config)
        self.classifier = NewsEventClassifier()
        self.impact_analyzer = NewsImpactAnalyzer()

    def build(self, snapshot: PortfolioSnapshot) -> tuple[List[NewsItem], List[NewsEvent], List[NewsImpact], str | None]:
        symbols = [position.asset.symbol for position in snapshot.positions]
        items = self.fetcher.fetch(symbols)
        events = self.classifier.classify(items)
        impacts = self.impact_analyzer.analyze(snapshot, events)
        summary = self._summary(items, events, impacts)
        return items, events, impacts, summary

    def _summary(self, items: List[NewsItem], events: List[NewsEvent], impacts: List[NewsImpact]) -> str | None:
        if not items:
            return None
        top_impacts = sorted(impacts, key=lambda item: item.news_impact, reverse=True)[:3]
        if not top_impacts:
            return f"{len(items)} news item(s) collected; no portfolio-relevant event impact identified."
        parts = [
            f"{impact.theme_key}: impact {impact.news_impact:.1f}/100 on {', '.join(impact.affected_symbols) or 'no direct holding'}"
            for impact in top_impacts
        ]
        return f"{len(items)} news item(s), {len(events)} classified event(s). Top impacts: " + "; ".join(parts)
