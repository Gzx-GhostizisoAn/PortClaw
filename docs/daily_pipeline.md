# Daily Pipeline

PortClaw runs a fixed daily pipeline. The pipeline can be triggered manually during development and scheduled later.

## Pipeline Steps

1. Load user configuration.
2. Load local holdings and watchlist.
3. Pull market bars and optional news.
4. Save raw data snapshots.
5. Normalize provider payloads into standard schemas.
6. Normalize news into `NewsItem`.
7. Classify news into `NewsEvent`.
8. Calculate portfolio-weighted `NewsImpact`.
9. Build `PortfolioSnapshot`.
10. Calculate `AssetMetrics`.
11. Calculate `PortfolioMetrics`.
12. Calculate `Exposure` and `StressTestResult`.
13. Run the signal generation layer.
14. Produce raw `Signal` objects with evidence.
15. Map signals, news impacts, and metrics into ranked `RiskTheme` objects.
16. Score each theme by metric contribution, signal severity, confidence, and news impact.
17. Assemble `DailyBrief`.
18. Send `DailyBrief` to the LLM report layer.
19. Persist portfolio snapshot, metrics, signals, themes, LLM input, LLM output, and audit metadata.

## Data Flow

```text
UserConfig + Holdings
  -> RawDataSnapshot
  -> MarketBar
  -> PortfolioSnapshot
  -> AssetMetrics + PortfolioMetrics + Exposure + StressTestResult
  -> NewsItem
  -> NewsEvent
  -> NewsImpact
  -> Signal rules
  -> Signal
  -> RiskThemeEngine
  -> ranked RiskTheme
  -> DailyBrief
  -> LLM Report
  -> AuditRecord
```

## Daily Output

The daily run should produce:

- A portfolio performance summary.
- A portfolio risk level.
- Top position risks.
- Top market risks.
- Strategy candidates.
- Items that need human review.
- A structured LLM input package.
- A final daily report.
