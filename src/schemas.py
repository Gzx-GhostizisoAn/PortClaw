from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AssetType(str, Enum):
    STOCK = "stock"
    ETF = "etf"
    FUND = "fund"
    BOND = "bond"
    CASH = "cash"
    CRYPTO = "crypto"
    OTHER = "other"


class SignalType(str, Enum):
    POSITION_RISK = "position_risk"
    MARKET_RISK = "market_risk"
    STRATEGY_SCAN = "strategy_scan"
    EVENT_RISK = "event_risk"
    COMPLIANCE = "compliance"


class NewsEventCategory(str, Enum):
    MACRO = "macro"
    INDUSTRY = "industry"
    COMPANY = "company"
    UNKNOWN = "unknown"


class NewsEventType(str, Enum):
    MACRO_USD = "macro_usd"
    MACRO_RATES = "macro_rates"
    MACRO_INFLATION = "macro_inflation"
    MACRO_OIL = "macro_oil"
    INDUSTRY_POLICY = "industry_policy"
    INDUSTRY_DEMAND = "industry_demand"
    INDUSTRY_SUPPLY_CHAIN = "industry_supply_chain"
    COMPANY_EARNINGS = "company_earnings"
    COMPANY_GUIDANCE = "company_guidance"
    COMPANY_REGULATORY = "company_regulatory"
    COMPANY_PRODUCT = "company_product"
    COMPANY_SENTIMENT = "company_sentiment"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RecommendedAction(str, Enum):
    HOLD = "hold"
    WATCH = "watch"
    REVIEW = "review"
    REDUCE_OR_REVIEW = "reduce_or_review"
    AVOID = "avoid"
    HUMAN_CONFIRMATION = "human_confirmation"


class Asset(BaseModel):
    symbol: str
    name: Optional[str] = None
    asset_type: AssetType = AssetType.STOCK
    currency: str = "USD"
    exchange: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    region: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Position(BaseModel):
    asset: Asset
    quantity: float
    average_cost: float
    market_price: Optional[float] = None
    market_value: Optional[float] = None
    weight: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    opened_at: Optional[date] = None
    tags: List[str] = Field(default_factory=list)


class PortfolioSnapshot(BaseModel):
    snapshot_id: str
    user_id: str = "local_user"
    as_of: datetime
    base_currency: str = "USD"
    positions: List[Position]
    cash: float = 0.0
    total_market_value: float = 0.0
    total_cost: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MarketBar(BaseModel):
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    provider: str
    adjusted_close: Optional[float] = None
    raw_snapshot_id: Optional[str] = None


class RawDataSnapshot(BaseModel):
    snapshot_id: str
    provider: str
    data_type: str
    requested_at: datetime
    request_params: Dict[str, Any] = Field(default_factory=dict)
    payload_hash: Optional[str] = None
    storage_path: Optional[str] = None
    status: str = "ok"
    error: Optional[str] = None


class AssetMetrics(BaseModel):
    symbol: str
    as_of: datetime
    daily_return: Optional[float] = None
    cumulative_return: Optional[float] = None
    volatility_20d: Optional[float] = None
    max_drawdown_60d: Optional[float] = None
    beta_to_benchmark: Optional[float] = None
    rsi_14: Optional[float] = None
    moving_average_20d: Optional[float] = None
    moving_average_60d: Optional[float] = None
    liquidity_score: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Exposure(BaseModel):
    exposure_type: str
    name: str
    weight: float
    symbols: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class StressTestResult(BaseModel):
    scenario_id: str
    title: str
    estimated_portfolio_change: float
    affected_symbols: List[str] = Field(default_factory=list)
    assumptions: Dict[str, Any] = Field(default_factory=dict)


class NewsItem(BaseModel):
    title: str
    content: str = ""
    source: str
    timestamp: datetime
    symbols: List[str] = Field(default_factory=list)
    url: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class NewsEvent(BaseModel):
    event_id: str
    event_type: NewsEventType
    category: NewsEventCategory
    title: str
    summary: str
    severity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    theme_keys: List[str] = Field(default_factory=list)
    symbols: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    source_news_index: int


class NewsImpact(BaseModel):
    impact_id: str
    event_id: str
    theme_key: str
    event_severity: float = Field(default=0.0, ge=0.0, le=1.0)
    portfolio_exposure: float = Field(default=0.0, ge=0.0, le=1.0)
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    news_impact: float = Field(default=0.0, ge=0.0, le=100.0)
    affected_symbols: List[str] = Field(default_factory=list)
    rationale: str = ""


class PortfolioMetrics(BaseModel):
    portfolio_id: str
    as_of: datetime
    total_return: Optional[float] = None
    daily_return: Optional[float] = None
    volatility_20d: Optional[float] = None
    max_drawdown_60d: Optional[float] = None
    concentration_score: Optional[float] = None
    largest_position_weight: Optional[float] = None
    sector_concentration_score: Optional[float] = None
    benchmark_symbol: Optional[str] = "SPY"
    beta_to_benchmark: Optional[float] = None
    exposures: List[Exposure] = Field(default_factory=list)
    stress_tests: List[StressTestResult] = Field(default_factory=list)


class Rule(BaseModel):
    rule_id: str
    name: str
    signal_type: SignalType
    description: str
    severity: Severity = Severity.MEDIUM
    enabled: bool = True
    thresholds: Dict[str, float] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Evidence(BaseModel):
    metric_name: str
    observed_value: Any
    threshold: Optional[Any] = None
    explanation: str


class Signal(BaseModel):
    signal_id: str
    rule_id: str
    signal_type: SignalType
    scope: str
    target: str
    severity: Severity
    title: str
    summary: str
    evidence: List[Evidence] = Field(default_factory=list)
    recommended_action: RecommendedAction = RecommendedAction.REVIEW
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    needs_human_review: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RiskThemeMetric(BaseModel):
    metric_name: str
    value: Any
    weight: float = Field(default=1.0, ge=0.0)
    contribution: float = Field(default=0.0, ge=0.0, le=1.0)
    source: str
    explanation: str


class RiskTheme(BaseModel):
    theme_id: str
    theme_key: str
    title: str
    severity: Severity
    summary: str
    priority_score: float = Field(default=0.0, ge=0.0, le=100.0)
    rank: Optional[int] = None
    metrics: List[RiskThemeMetric] = Field(default_factory=list)
    drivers: List[str] = Field(default_factory=list)
    signal_ids: List[str] = Field(default_factory=list)
    source_types: List[str] = Field(default_factory=list)
    recommended_action: RecommendedAction = RecommendedAction.REVIEW
    needs_human_review: bool = False


class DailyBrief(BaseModel):
    brief_id: str
    as_of: datetime
    portfolio_snapshot: PortfolioSnapshot
    portfolio_metrics: PortfolioMetrics
    asset_metrics: List[AssetMetrics] = Field(default_factory=list)
    signals: List[Signal] = Field(default_factory=list)
    risk_themes: List[RiskTheme] = Field(default_factory=list)
    strategy_candidates: List[Signal] = Field(default_factory=list)
    news_items: List[NewsItem] = Field(default_factory=list)
    news_events: List[NewsEvent] = Field(default_factory=list)
    news_impacts: List[NewsImpact] = Field(default_factory=list)
    news_summary: Optional[str] = None
    human_review_items: List[str] = Field(default_factory=list)
    disclaimer: str = "This report is for research and educational purposes only and is not financial advice."


class AuditRecord(BaseModel):
    audit_id: str
    created_at: datetime
    raw_snapshot_ids: List[str] = Field(default_factory=list)
    portfolio_snapshot_id: str
    metric_object_ids: List[str] = Field(default_factory=list)
    signal_ids: List[str] = Field(default_factory=list)
    risk_theme_ids: List[str] = Field(default_factory=list)
    llm_input: Optional[Dict[str, Any]] = None
    llm_output: Optional[str] = None
    storage_paths: Dict[str, str] = Field(default_factory=dict)
