# Holding Input Strategy

The agent needs two different kinds of data:

1. Private holdings: what the user owns, cost basis, quantity, cash.
2. Public market data: prices, indicators, news, fundamentals.
3. Private trade history: what the user bought or sold, at what price, and when.

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
- Trade CSV import that updates the local holdings snapshot.
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

### 3. Trade CSV Import For Active Trading

For high-frequency or active trading workflows, holdings should be treated as a state derived from trades rather than a permanently static file.

Create the template:

```bash
python agent.py trade-template
```

Fill:

```text
data/trade_template.csv
```

Import and sync:

```bash
python agent.py import-trades --csv data/trade_template.csv
```

The trade file accepts:

- `traded_at`
- `side`
- `symbol`
- `name`
- `sector`
- `quantity`
- `price`
- `fees`

The import command reads the current `data/portfolio.local.json` if present, otherwise it falls back to `data/portfolio.example.json`. It applies buy/sell rows and writes updated holdings back to `data/portfolio.local.json` by default.

Buy rows:

- increase position quantity
- update weighted average cost
- reduce cash by trade value plus fees
- refresh local fallback market price

Sell rows:

- reduce position quantity
- keep average cost for the remaining position
- increase cash by proceeds minus fees
- calculate realized P&L
- remove a position when quantity reaches zero

Each applied trade is appended to:

```text
data/trades.local.jsonl
```

This JSONL file is private local behavior data. It is intended for later model features such as user profiling, turnover analysis, preferred sectors, realized P&L discipline, and risk appetite inference.

### 4. Future Brokerage Export Import

Many broker apps can export or copy positions as table text or CSV-like files. The next practical step is to add import profiles:

- Eastmoney export profile.
- Tonghuashun export profile.
- Generic broker CSV profile.
- Manual paste parser.

## Market Data Direction

For public prices and indicators, the project can later add adapters such as:

- Yahoo Finance/yfinance as a free public source.
- AKShare for China-market public data, including many public Eastmoney/Tonghuashun-style interfaces.
- efinance for free China-market public quote and history data.
- CCXT for crypto public market data, with exchange credentials only when private account/trading APIs are needed.
- FRED for macro series with a FRED API key.
- Financial Modeling Prep, Tushare, Alpha Vantage, RQData, EODHD, and Twelve Data for credentialed market, macro, or fundamental data.
- Eastmoney public quote endpoints through a dedicated adapter.
- Commercial providers such as EODHD or Twelve Data.

The boundary should stay clear:

```text
Local holdings input -> private ledger
Trade rows -> private behavior log and updated holdings
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

Run `python agent.py data-sources` to see whether each configured source is implemented, planned, free, public, or credentialed.

The LLM should never be asked to infer holdings from screenshots, chat text, or raw brokerage pages without structured confirmation.
