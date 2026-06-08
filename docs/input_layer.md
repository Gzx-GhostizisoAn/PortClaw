# Input Layer

PortClaw supports beginner-friendly input commands and one private local input file.

Recommended command:

```bash
python agent.py holdings
```

CSV path:

```bash
python agent.py portfolio-template
python agent.py import-holdings --csv data/portfolio_template.csv
```

The generated private file is:

```text
data/portfolio.local.json
```

It is ignored by git.

The fallback example file is:

```text
data/portfolio.example.json
```

These files describe what the user holds and what the agent should scan.

## Holdings

`positions` are real holdings in the user's local ledger:

```json
{
  "symbol": "AAPL",
  "name": "Apple Inc.",
  "sector": "Technology",
  "quantity": 10,
  "average_cost": 175.0,
  "market_price": 210.0
}
```

Meaning:

- `symbol`: ticker or asset identifier.
- `quantity`: how many shares or units the user holds.
- `average_cost`: private cost basis.
- `market_price`: latest price used by the local demo adapter.
- `sector`: used for exposure analysis.

The agent calculates:

```text
market_value = quantity * market_price
unrealized_pnl = market_value - quantity * average_cost
weight = market_value / total_portfolio_value
```

## Watchlist

`watchlist` assets are not holdings. They are scanned for strategy candidates:

```json
{
  "symbol": "NVDA",
  "latest_price": 1160.0,
  "moving_average_20d": 1120.0,
  "moving_average_60d": 1080.0,
  "volatility_20d": 0.039
}
```

## Quick Commands

```bash
python agent.py holdings
python agent.py portfolio-template
python agent.py import-holdings --csv data/portfolio_template.csv
python agent.py portfolio
python agent.py daily
python agent.py ask "Why is my portfolio risky today?"
python agent.py chat
```

Use a custom portfolio file:

```bash
python agent.py daily --portfolio data/my_portfolio.json
python agent.py ask "What is my largest risk?" --portfolio data/my_portfolio.json
```
