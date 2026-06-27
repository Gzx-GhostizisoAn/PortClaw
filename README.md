# PortClaw

PortClaw is a local-first financial research agent for portfolio risk monitoring, news-aware risk theme analysis, daily brief generation, and auditable LLM-assisted reporting.

It is designed around one core principle:

```text
Analytics, rules, risk themes, and news impact models produce judgments first.
The LLM explains structured conclusions afterward.
```

PortClaw is not a web product. It runs locally with private portfolio files, local audit storage, CLI chat, JSONL message gateways, Telegram Bot API support, configurable market-data providers, and optional OpenAI-compatible LLM reporting.

## Core Capabilities

- Local holdings input through an interactive wizard or CSV import.
- Trade CSV import that updates holdings, cash, cost basis, realized P&L, and a local behavior log.
- Market-data abstraction with Yahoo Finance/yfinance history enrichment.
- Deterministic portfolio metrics, exposures, and stress scenarios.
- Raw rule signals with structured evidence.
- A risk theme engine that ranks concentration, volatility, liquidity, macro, and news/event risk.
- A news layer that normalizes news, classifies events, maps events to themes, and calculates portfolio-weighted impact.
- Local template reporting or optional OpenAI-compatible LLM reporting.
- Local audit trail for `DailyBrief`, LLM input, LLM output, and metadata.
- CLI chat plus local JSONL and Telegram message-channel adapters.

## Daily Analysis Flow

1. Load local configuration and private holdings.
2. Pull market data from the configured provider.
3. Normalize market data and build a `PortfolioSnapshot`.
4. Calculate `AssetMetrics`, `PortfolioMetrics`, exposures, and stress scenarios.
5. Collect news and normalize it into `NewsItem`.
6. Classify news into `NewsEvent`.
7. Calculate portfolio-weighted `NewsImpact`.
8. Run rule and risk models to produce raw `Signal` objects.
9. Map metrics, signals, and news impacts into ranked `RiskTheme` objects.
10. Assemble a structured `DailyBrief`.
11. Generate a local or LLM-assisted report from the structured brief.
12. Save the audit record locally.

## Quick Start

```bash
cd PortClaw
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python agent.py init
python agent.py setup
python agent.py status
python agent.py daily
```

`python agent.py init` creates local runtime files from safe templates. Do not commit generated private files such as `config/local_config.json`, `.env`, `audit_runs/`, or `messages/`.

## Open The Desktop App

Build and install the macOS app bundle:

```bash
scripts/build_macos_app.sh
open "$HOME/Applications/PortClaw.app"
```

After this, PortClaw opens like a normal Mac app from Finder. The bundle launches a native desktop window and keeps the local Python runtime behind the app boundary.

Build a standalone PyInstaller app bundle:

```bash
scripts/build_pyinstaller_app.sh
open dist/PortClaw.app
```

The PyInstaller bundle includes the Python runtime and dependencies inside `dist/PortClaw.app`. Runtime config, holdings, trade logs, and templates are stored under `~/Library/Application Support/PortClaw/runtime`.

## Developer Commands

Start the interactive menu UI:

```bash
python agent.py menu
python agent.py ui
```

Start the local Web App UI during development:

```bash
python app.py
```

Then open `http://127.0.0.1:8765`. The app is a local wrapper around the existing PortClaw runtime, so commands such as status, daily brief generation, portfolio explanation, and free-form questions still use `agent.py` and the same private local config/portfolio files.

Start the local desktop window UI during development:

```bash
python desktop_app.py
```

This uses pywebview to show the same local PortClaw interface inside a native desktop window.

The UI includes a finance-first dashboard with portfolio value, period returns, risk level, allocation charts, holding weights, exposure analysis, agent alerts, and optimization suggestions. It also includes pages for daily risk reports, free-form questions, holdings editing, trade history, data-source status, and local model/data-source configuration.

The Trade History page supports `Buy`, `Sell`, `Dividend`, `Deposit`, and `Withdraw` events. Trades update local holdings, cash, cost basis, realized P&L, and the private local behavior log.

Desktop launcher sources live under `launchers/macos/`; the generated app bundle should not be committed.

```bash
python agent.py holdings
python agent.py portfolio-template
python agent.py import-holdings --csv data/portfolio_template.csv
python agent.py trade-template
python agent.py import-trades --csv data/trade_template.csv
python agent.py trade-log
python agent.py portfolio
python agent.py daily
python agent.py ask "Why is my portfolio risky today?"
python agent.py chat
```

Interactive chat accepts short commands such as:

```text
status
daily
portfolio
help
```

Any other chat text is treated as a portfolio question. If a remote LLM provider is configured with a key, PortClaw sends the structured `DailyBrief` plus the user question to that model. If the provider is configured but the key/client/API call is unavailable, the response says that the remote LLM was not used and shows the local fallback instead.

## Configuration

PortClaw reads local configuration from `config/local_config.json`. You can create it from the safe template with:

```bash
python agent.py init
```

The file is private runtime state and is ignored by git. API keys can be stored either in `config/local_config.json` or in `.env`; environment variables take priority when present.

Use the setup wizard for the easiest interactive configuration:

```bash
python agent.py setup
```

Inspect the active config with secrets masked:

```bash
python agent.py config-show
```

List supported model and data-source options:

```bash
python agent.py models
python agent.py data-sources
```

### Config File Fields

`config/local_config.json` has these top-level sections:

| Field | Meaning |
| --- | --- |
| `user_id` | Local user identifier written into portfolio snapshots and audit records. |
| `base_currency` | Reporting currency label, such as `USD`, `CNY`, or `HKD`. PortClaw does not yet do FX conversion automatically. |
| `llm` | Model provider settings for report generation and question answering. |
| `channels` | Message input/output channels such as CLI, local JSONL, or Telegram. |
| `market_data` | Public market-data provider used for price/history/news enrichment. |
| `storage` | Local folders for audit files and message gateway files. |
| `risk_preferences` | User-adjustable thresholds for concentration and volatility rules. |

Example:

```json
{
  "user_id": "local_user",
  "base_currency": "USD",
  "llm": {
    "provider": "local_template",
    "model": "local-template",
    "api_key": "",
    "base_url": ""
  },
  "market_data": {
    "provider": "demo",
    "api_key": "",
    "base_url": "",
    "mode": "local"
  },
  "storage": {
    "audit_dir": "audit_runs",
    "message_dir": "messages"
  },
  "risk_preferences": {
    "max_single_position_weight": 0.25,
    "high_volatility_20d": 0.04,
    "max_largest_position_weight": 0.35
  }
}
```

### LLM Settings

`llm.provider` controls who writes the final narrative report:

| Provider | Key Needed | Notes |
| --- | --- | --- |
| `local_template` | No | Deterministic local report, no network model call. |
| `qwen` | Yes | OpenAI-compatible DashScope endpoint by default. |
| `openai` | Yes | Uses the OpenAI Python client. |
| `deepseek` | Yes | Uses the DeepSeek OpenAI-compatible endpoint. |
| `openai_compatible` | Yes | For any custom OpenAI-compatible endpoint; set `model` and `base_url`. |

`llm.model` is the model name sent to the provider. `llm.api_key` is the provider token. `llm.base_url` is usually blank unless the provider uses an OpenAI-compatible custom endpoint.

Configure an LLM provider:

```bash
python agent.py configure --llm-provider qwen --llm-model qwen-max --llm-api-key "YOUR_QWEN_KEY" --llm-base-url "https://dashscope.aliyuncs.com/compatible-mode/v1"
python agent.py configure --llm-provider openai --llm-model gpt-4o-mini --llm-api-key "YOUR_OPENAI_KEY"
python agent.py configure --llm-provider deepseek --llm-model deepseek-v4-flash --llm-api-key "YOUR_DEEPSEEK_KEY"
python agent.py configure --llm-provider openai_compatible --llm-model "your-model" --llm-api-key "YOUR_KEY" --llm-base-url "http://localhost:11434/v1"
```

In chat, exact commands such as `status`, `daily`, and `portfolio` run local commands. Free-form questions such as `what is my portfolio status?` or `我现在组合最大的风险是什么？` go through the model-backed question path when the LLM is ready.

### Market Data Settings

`market_data.provider` selects the public data source. `market_data.api_key` stores a provider key, token, or account credential when required. `market_data.base_url` is for custom endpoints and is normally blank. `market_data.mode` is normalized from the provider category, such as `local`, `free`, `macro`, `freemium`, or `commercial`.

Configure market data:

```bash
python agent.py configure --market-provider yahoo
python agent.py configure --market-provider fred --market-api-key "YOUR_FRED_KEY"
python agent.py configure --market-provider fmp --market-api-key "YOUR_FMP_KEY"
```

Environment variables in `.env` are also supported:

```text
QWEN_API_KEY=
OPENAI_API_KEY=
DEEPSEEK_API_KEY=
EODHD_API_KEY=
TWELVE_DATA_API_KEY=
FRED_API_KEY=
FMP_API_KEY=
TUSHARE_TOKEN=
ALPHA_VANTAGE_API_KEY=
RQDATA_USERNAME=
RQDATA_PASSWORD=
CCXT_EXCHANGE=
CCXT_API_KEY=
CCXT_SECRET=
```

When multiple market-data environment variables are set, PortClaw uses the first match in this priority order: `EODHD_API_KEY`, `TWELVE_DATA_API_KEY`, `FRED_API_KEY`, `FMP_API_KEY`, `TUSHARE_TOKEN`, `ALPHA_VANTAGE_API_KEY`, then `RQDATA_USERNAME` plus `RQDATA_PASSWORD`.

### Channel Settings

Each channel entry has:

| Field | Meaning |
| --- | --- |
| `channel_id` | Local name, for example `local_cli`, `local_jsonl`, or `telegram_personal`. |
| `channel_type` | Adapter type such as `cli`, `jsonl`, or `telegram`. |
| `enabled` | Whether the channel should run. |
| `credentials` | Secret values such as a Telegram bot token. These are masked by `config-show`. |
| `options` | Adapter-specific settings such as JSONL inbox/outbox paths or polling timeout. |

Configure a Telegram channel:

```bash
python agent.py configure-channel --channel-id telegram_personal --channel-type telegram --credential bot_token="YOUR_TELEGRAM_BOT_TOKEN" --option timeout=20
```

### Risk Preferences

`risk_preferences` controls deterministic rule thresholds:

| Field | Meaning |
| --- | --- |
| `max_single_position_weight` | Position weight above this level triggers single-name concentration review. |
| `high_volatility_20d` | 20-day volatility above this level is treated as high volatility. |
| `max_largest_position_weight` | Largest-position threshold used in portfolio-level concentration scoring. |

## Market Data And News

Current market-data providers and status:

| Provider | Status | Auth | Intended Use |
| --- | --- | --- | --- |
| `demo` | Implemented | None | Local sample data for testing. |
| `yahoo` | Implemented | None | Free public history and yfinance news. |
| `akshare` | Planned | None | China-market public data through AKShare. |
| `efinance` | Planned | None | China-market public quote/history data through efinance. |
| `ccxt` | Planned | Public market data usually keyless | Crypto exchange OHLCV/tickers; private account/trading needs exchange credentials. |
| `fred` | Planned | `FRED_API_KEY` | Macro series from FRED. |
| `fmp` | Planned | `FMP_API_KEY` | Prices, fundamentals, ratios, calendars, and market data from Financial Modeling Prep. |
| `tushare` | Implemented | `TUSHARE_TOKEN` | Tushare Pro China-market daily history for symbols such as `600519.SH`, `000001.SZ`, or six-digit A-share codes. |
| `alpha_vantage` | Planned | `ALPHA_VANTAGE_API_KEY` | Market, FX, crypto, fundamental, and macro endpoints. |
| `rqdata` | Planned | Account/license credentials | Ricequant/RQData China-market data. |
| `eodhd` | Planned | `EODHD_API_KEY` | Commercial EOD, fundamentals, and news data. |
| `twelve_data` | Planned | `TWELVE_DATA_API_KEY` | Commercial unified market data. |

Run `python agent.py data-sources` to see each provider's category, implementation status, auth type, and supported environment variables.

Current news layer:

- yfinance news collection when the market provider is `yahoo`.
- Unified `NewsItem` schema.
- Keyword event classification into macro, industry, and company events.
- Portfolio-specific impact scoring with nonlinear amplification:

```text
base_impact = event_severity * portfolio_exposure * relevance_score
news_impact = base_impact * amplification_factor
```

The amplification factor raises event risk when severity, portfolio exposure, repeated similar events, or negative sentiment can make the outcome nonlinear.

SEC, AKShare, efinance, FMP, Alpha Vantage, EODHD, and Twelve Data news adapters can be added behind the same `NewsItem` contract.

## Dependencies

`requirements.txt` includes the core runtime, the implemented Yahoo/yfinance and Tushare adapters, the OpenAI-compatible LLM client, and planned data-source clients for AKShare, efinance, CCXT, FRED, Alpha Vantage, and RQData.

If an optional commercial SDK is unavailable for your platform or subscription, the corresponding provider can still be represented in config, but its adapter should fail clearly rather than silently fabricating data.

## Holdings Input

Use the guided holdings wizard:

```bash
python agent.py holdings
```

At the symbol prompt, these commands are available:

| Command | Meaning |
| --- | --- |
| `save` or `done` | Stop entering positions, review the list, and save. |
| `cancel`, `exit`, or `quit` | Exit without saving. |
| `list` | Show positions already entered in this session. |
| `remove` | Remove the last entered position. |
| `remove 2` | Remove a specific row from the entered list. |

The wizard saves to `data/portfolio.local.json` by default. This file is private local state and is ignored by git.

## Trade Import And Live Holdings Sync

For faster trading environments, do not keep `data/portfolio.local.json` as a static snapshot. Import trade rows whenever the user has new buys or sells:

```bash
python agent.py trade-template
python agent.py import-trades --csv data/trade_template.csv
python agent.py trade-log
```

The trade CSV supports these columns:

| Field | Meaning |
| --- | --- |
| `traded_at` | Trade timestamp. Optional; current time is used if blank. |
| `side` | `buy` / `sell`, or `买入` / `卖出`. |
| `symbol` | Stock or ETF code. |
| `name` | Company/security name. |
| `sector` | Sector label used by exposure analysis. |
| `quantity` | Shares/units bought or sold. |
| `price` | Buy or sell execution price. |
| `fees` | Commission, tax, or other transaction costs. |

`import-trades` reads the current portfolio, applies each row, and writes the updated holdings back to `data/portfolio.local.json` by default. Buys increase quantity, update weighted average cost, reduce cash, and refresh local market price. Sells reduce quantity, increase cash, calculate realized P&L, and remove fully exited positions.

Every applied row is also appended to `data/trades.local.jsonl` as a private behavior log. That log is intended for later user profiling, such as turnover, holding period, preferred sectors, risk appetite, and stop-loss/take-profit behavior. It is ignored by git.

## Message Channels

Local JSONL gateway:

```bash
python agent.py message --text "daily risk brief"
python agent.py gateway --channel local_jsonl --once
tail -n 1 messages/outbox.jsonl
```

Telegram Bot API gateway:

```bash
python agent.py configure-channel --channel-id telegram_personal --channel-type telegram --credential bot_token="YOUR_TELEGRAM_BOT_TOKEN" --option timeout=20
python agent.py gateway --channel telegram_personal
```

List supported channel types:

```bash
python agent.py channels
```

## Project Structure

```text
PortClaw/
  README.md
  agent.py
  requirements.txt
  .env.example
  .gitignore
  CONTRIBUTING.md
  LICENSE
  SECURITY.md
  config/
    local_config.example.json
  data/
    portfolio.example.json
    portfolio_template.csv
  docs/
    architecture.md
    channel_runtime.md
    channels.md
    daily_pipeline.md
    holding_input_strategy.md
    input_layer.md
    local_deployment.md
    news_layer.md
    open_source.md
    project_map.md
  examples/
    demo_daily_run.py
  src/
    __init__.py
    agent_runtime.py
    audit.py
    channel_runner.py
    cli.py
    config.py
    message_chat.py
    pipeline.py
    portfolio_input.py
    sample_data.py
    schemas.py
    analytics/
      __init__.py
      exposures.py
      metrics.py
      signals.py
    channels/
      __init__.py
      base.py
      jsonl.py
      telegram.py
    commands/
      __init__.py
      channel_commands.py
      common.py
      configuration.py
      holdings.py
      menu.py
      runtime.py
    data/
      __init__.py
      news.py
      market_data/
        __init__.py
        base.py
        client.py
        metrics.py
        yahoo.py
    intelligence/
      __init__.py
      risk_theme_engine.py
    ledger/
      __init__.py
      portfolio_loader.py
    reporting/
      __init__.py
      report_generator.py
```

## Documentation

- [Architecture](docs/architecture.md)
- [Daily pipeline](docs/daily_pipeline.md)
- [News layer](docs/news_layer.md)
- [Portfolio input layer](docs/input_layer.md)
- [Holding input strategy](docs/holding_input_strategy.md)
- [Channel runtime](docs/channel_runtime.md)
- [Local deployment](docs/local_deployment.md)
- [Open-source readiness](docs/open_source.md)
- [Project map](docs/project_map.md)

## Open Source Safety

Safe templates are included:

- `.env.example`
- `config/local_config.example.json`
- `data/portfolio.example.json`
- `data/portfolio_template.csv`

Local private files are ignored by git:

- `.env`
- `config/local_config.json`
- `data/portfolio.local.json`
- `data/trades.local.jsonl`
- `audit_runs/`
- `messages/`

See [SECURITY.md](SECURITY.md) and [open_source.md](docs/open_source.md) before publishing.

## Roadmap

- Add SEC and AKShare news adapters behind the `NewsItem` contract.
- Add EODHD, Twelve Data, and AKShare market-data adapters.
- Expand risk theme taxonomy and event classification rules.
- Add broker/export importers under `src/portfolio_input.py` or a future `src/importers/` package.
- Add transaction-behavior analytics from `data/trades.local.jsonl`.
- Add scheduled daily runs.
- Add more external channel adapters under `src/channels/`.
