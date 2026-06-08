# Architecture Baseline

This project uses a layered local-agent architecture narrowed to financial research workflows.

## 1. Data Access Layer

Responsibilities:

- Pull data from public, commercial, or local sources.
- Validate whether requested data exists.
- Save raw snapshots with provider, symbol, timestamp, and request metadata.
- Avoid analytics and business judgment.

Output examples:

- `RawDataSnapshot`
- raw OHLCV payloads
- raw news payloads

Current implementation:

- `src/data/market_data/base.py`: normalized provider result contract.
- `src/data/market_data/client.py`: provider switch and fallback routing.
- `src/data/market_data/yahoo.py`: Yahoo Finance/yfinance adapter.
- `src/data/market_data/metrics.py`: market-history to metric conversion.

## 2. Normalization Layer

Responsibilities:

- Convert provider-specific fields into unified schemas.
- Standardize symbol, date, currency, region, and asset type.
- Mark missing, stale, or suspicious values.

Output examples:

- `Asset`
- `MarketBar`

Current implementation:

- Provider-specific OHLCV columns are normalized to lowercase `date`, `open`, `high`, `low`, `close`, `volume`.
- Missing provider data is carried forward as explicit metadata instead of being silently hidden.

## 3. Portfolio Ledger Layer

Responsibilities:

- Represent what the user holds.
- Resolve quantity, cost basis, market value, and weight.
- Separate holdings from watchlist assets.
- Preserve private local portfolio data.

Output examples:

- `Position`
- `PortfolioSnapshot`

Current implementation:

- `src/ledger/portfolio_loader.py`: loads local holdings, enriches prices when market adapters work, and builds `PortfolioSnapshot`.
- `src/portfolio_input.py`: interactive holdings wizard and CSV import helpers.

## 4. Metrics Layer

Responsibilities:

- Calculate asset-level metrics.
- Calculate portfolio-level metrics.
- Calculate exposures and stress scenarios.
- Avoid generating advice.

Output examples:

- `AssetMetrics`
- `PortfolioMetrics`
- `Exposure`
- `StressTestResult`

Current implementation:

- `src/analytics/metrics.py`: portfolio-level metrics.
- `src/analytics/exposures.py`: exposures and basic stress scenarios.
- `src/data/market_data/metrics.py`: asset metric calculation from market bars.

## 5. News Data And Event Layer

Responsibilities:

- Fetch or receive news from sources such as yfinance, SEC, AKShare, or commercial feeds.
- Normalize all items into `NewsItem`.
- Classify each item into macro, industry, or company events.
- Map events to risk themes.
- Calculate portfolio-specific news impact.

Output examples:

- `NewsItem`
- `NewsEvent`
- `NewsImpact`

Current implementation:

- `src/data/news.py`: yfinance news collection, keyword event classification, theme mapping, and portfolio exposure weighting.

## 6. Signal Generation Layer

Responsibilities:

- Turn metrics into raw structured signals.
- Apply threshold rules and model outputs.
- Preserve evidence for each triggered signal.
- Avoid final prioritization or narrative judgment.

Output examples:

- `Rule`
- `Signal`

Current implementation:

- `src/analytics/signals.py`: threshold rules and strategy scan signals.

## 7. Intelligence Layer

Responsibilities:

- Map raw signals, news impacts, and metrics into risk themes.
- Score and rank themes by metric contribution, signal severity, confidence, and portfolio-weighted news impact.
- Keep the theme taxonomy explicit, such as concentration, volatility, liquidity, macro, and news/event risk.
- Produce the structured conclusion that the LLM is allowed to explain.

Output examples:

- `RiskTheme`
- `RiskThemeMetric`

Current implementation:

- `src/intelligence/risk_theme_engine.py`: theme definitions, signal-to-theme mapping, metric scoring, priority ranking, and driver summaries.

## 8. Conclusion Orchestration Layer

Responsibilities:

- Assemble the machine-readable daily conclusion.
- Identify human review items from high-priority themes and high-severity signals.
- Keep strategy candidates separate from risk themes.

Output examples:

- `DailyBrief`

Current implementation:

- `src/pipeline.py`: portfolio metrics, rule evaluation, risk theme engine orchestration, and `DailyBrief` assembly.

## 9. Explanation And Reporting Layer

Responsibilities:

- Accept only structured conclusions.
- Generate human-readable daily reports.
- Add clear disclaimers.
- Avoid direct raw-data interpretation by the LLM.

Output examples:

- LLM prompt input
- final daily report

Current implementation:

- `src/reporting/report_generator.py`: local template reports and OpenAI-compatible API calls for Qwen, OpenAI, DeepSeek, or custom local endpoints.

## 10. Frontend, Digest, And Notification Layer

Responsibilities:

- Provide local CLI chat, message gateway, scheduled runs, and optional external messaging channels.
- Keep the first usable interface local and scriptable instead of web-first.
- Add web UI later only as a presentation layer over the same auditable runtime.

Current implementation:

- `src/cli.py`: parser-only CLI entry.
- `src/commands/`: command implementations split by concern.
- `src/channels/`: local JSONL and Telegram channel adapters.
- `src/channel_runner.py`: gateway loop.

## System Principle

```text
LLM is downstream of analytics, not upstream of judgment.
```

The LLM reads `DailyBrief`, not raw market data or private transaction records.
