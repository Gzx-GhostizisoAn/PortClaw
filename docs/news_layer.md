# News Layer

The news layer turns unstructured headlines and article snippets into portfolio-weighted risk inputs.

## Flow

```text
News source
  -> NewsItem
  -> NewsEvent
  -> NewsImpact
  -> RiskThemeEngine
  -> DailyBrief
  -> LLM explanation
```

## 1. Unified News Format

All sources should normalize into:

```python
NewsItem(
    title,
    content,
    source,
    timestamp,
    symbols,
)
```

The current implementation supports yfinance news when the configured market-data provider is `yahoo`. SEC, AKShare, and commercial sources can be added behind the same `NewsItem` contract.

## 2. Event Classification

`NewsEventClassifier` uses keyword rules to classify each item into:

- macro events, such as rates, inflation, USD, and oil.
- industry events, such as policy, demand, and supply chain.
- company events, such as earnings, guidance, regulatory, product, and sentiment.

The classifier assigns:

- `event_type`
- `category`
- `severity_score`
- `theme_keys`
- matched keywords

## 3. Risk Theme Mapping

Each event maps to one or more risk themes:

- `macro_risk`
- `news_risk`
- `volatility_risk`
- `liquidity_risk`
- `concentration_risk`

Signals remain separate evidence. News enters through `NewsImpact`, so the theme engine can compare news-driven risk against metric-driven and rule-driven risk.

## 4. Portfolio Relevance Weighting

News impact is portfolio-specific and nonlinear:

```text
base_impact = event_severity * portfolio_exposure * relevance_score
news_impact = base_impact * amplification_factor
```

The amplification factor increases risk when event severity is high, the portfolio has concentrated exposure, similar events are clustered, or the event is classified as negative sentiment.

Examples:

- A US AI chip export restriction has low relevance to a bank or insurance ETF portfolio.
- The same event has high relevance to a portfolio concentrated in NVDA, AMD, TSM, or semiconductor exposure.

The current implementation checks:

- direct symbol overlap.
- industry/sector keyword overlap.
- macro event exposure across invested portfolio weight.

## 5. Theme Engine Integration

`RiskThemeEngine` uses news impact alongside metrics and raw rule signals:

```text
priority_score = metric_score * 50% + signal_score * 25% + news_impact_score * 25%
```

The LLM receives the final ranked `risk_themes` plus the underlying `news_layer` details. It explains structured conclusions only; it does not classify raw news on its own.
