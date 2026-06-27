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
  "symbol": "SYMBOL",
  "name": "Asset name",
  "sector": "Sector",
  "quantity": 0,
  "average_cost": 0.0
}
```

Meaning:

- `symbol`: ticker or asset identifier.
- `quantity`: how many shares or units the user holds.
- `average_cost`: private cost basis.
- `sector`: used for exposure analysis.

The agent calculates:

```text
close_price = latest completed close from the configured market data provider
market_value = quantity * close_price
unrealized_pnl = market_value - quantity * average_cost
weight = market_value / total_portfolio_value
```

Users should not maintain live stock prices in the holdings file. If provider
history is unavailable, PortClaw marks return metrics as unavailable and only
uses cost basis as a conservative fallback for structure displays.

## Watchlist

`watchlist` assets are not holdings. They are scanned for strategy candidates:

```json
{
  "symbol": "SYMBOL",
  "latest_price": 0.0,
  "moving_average_20d": 0.0,
  "moving_average_60d": 0.0,
  "volatility_20d": 0.0
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
