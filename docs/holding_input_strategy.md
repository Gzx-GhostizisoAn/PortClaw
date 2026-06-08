# Holding Input Strategy

The agent needs two different kinds of data:

1. Private holdings: what the user owns, cost basis, quantity, cash.
2. Public market data: prices, indicators, news, fundamentals.

These should not be mixed.

## Why Not Directly Read Eastmoney Or Tonghuashun Accounts First?

Eastmoney and Tonghuashun are useful public market-data sources, but personal account holdings are different. Reading account holdings usually requires login sessions, broker account authorization, export files, or automation around desktop/mobile clients.

For an open-source local agent, directly scraping personal account holdings creates problems:

- Fragile login and cookie/session handling.
- Potential account-security risk.
- Platform policy and compliance uncertainty.
- Different brokers and account types expose different export formats.
- Hard to make reliable for beginner users.

So PortClaw starts with local-first input:

- Interactive holdings wizard.
- CSV import.
- Brokerage export normalization later.

## Input Methods

### 1. Interactive Wizard

```bash
python agent.py holdings
```

This asks the user for:

- symbol
- name
- sector
- quantity
- average cost
- latest market price
- cash balance

It saves private data to:

```text
data/portfolio.local.json
```

This file is ignored by git.

### 2. CSV Template

```bash
python agent.py portfolio-template
```

Then fill:

```text
data/portfolio_template.csv
```

Import it:

```bash
python agent.py import-holdings --csv data/portfolio_template.csv
```

### 3. Future Brokerage Export Import

Many broker apps can export or copy positions as table text or CSV-like files. The next practical step is to add import profiles:

- Eastmoney export profile.
- Tonghuashun export profile.
- Generic broker CSV profile.
- Manual paste parser.

## Market Data Direction

For public prices and indicators, the project can later add adapters such as:

- Yahoo Finance/yfinance as a free public source.
- AKShare for China-market public data, including many public Eastmoney/Tonghuashun-style interfaces.
- Eastmoney public quote endpoints through a dedicated adapter.
- Commercial providers such as EODHD or Twelve Data.

The boundary should stay clear:

```text
Local holdings input -> private ledger
Public market data -> price/news/fundamental enrichment
```

The selected market-data provider is stored in:

```text
config/local_config.json
```

Example free source:

```bash
python agent.py configure --market-provider yahoo
```

Example commercial source:

```bash
python agent.py configure --market-provider eodhd --market-api-key "YOUR_EODHD_KEY"
```

The LLM should never be asked to infer holdings from screenshots, chat text, or raw brokerage pages without structured confirmation.
