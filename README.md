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

## Common Commands

Start the interactive menu UI:

```bash
python agent.py menu
python agent.py ui
```

```bash
python agent.py holdings
python agent.py portfolio-template
python agent.py import-holdings --csv data/portfolio_template.csv
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

## Configuration

Use the setup wizard for the easiest local configuration:

```bash
python agent.py setup
```

List supported model and data-source options:

```bash
python agent.py models
python agent.py data-sources
```

Configure market data:

```bash
python agent.py configure --market-provider yahoo
python agent.py configure --market-provider eodhd --market-api-key "YOUR_EODHD_KEY"
```

Configure an LLM provider:

```bash
python agent.py configure --llm-provider qwen --llm-model qwen-max --llm-api-key "YOUR_QWEN_KEY" --llm-base-url "https://dashscope.aliyuncs.com/compatible-mode/v1"
python agent.py configure --llm-provider openai --llm-model gpt-4o-mini --llm-api-key "YOUR_OPENAI_KEY"
python agent.py configure --llm-provider deepseek --llm-model deepseek-v4-flash --llm-api-key "YOUR_DEEPSEEK_KEY"
python agent.py configure --llm-provider openai_compatible --llm-model "your-model" --llm-api-key "YOUR_KEY" --llm-base-url "http://localhost:11434/v1"
```

Environment variables in `.env` are also supported:

```text
QWEN_API_KEY=
OPENAI_API_KEY=
DEEPSEEK_API_KEY=
EODHD_API_KEY=
TWELVE_DATA_API_KEY=
```

## Market Data And News

Current market-data providers:

- `demo`: local sample data for testing.
- `yahoo`: free public market data through Yahoo Finance/yfinance.
- `akshare`: configured option for China-market public data adapters.
- `eodhd`: configured commercial provider option.
- `twelve_data`: configured commercial provider option.

Current news layer:

- yfinance news collection when the market provider is `yahoo`.
- Unified `NewsItem` schema.
- Keyword event classification into macro, industry, and company events.
- Portfolio-specific impact scoring:

```text
news_impact = event_severity * portfolio_exposure * relevance_score
```

SEC, AKShare, EODHD, and Twelve Data news adapters can be added behind the same `NewsItem` contract.

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
- `audit_runs/`
- `messages/`

See [SECURITY.md](SECURITY.md) and [open_source.md](docs/open_source.md) before publishing.

## Roadmap

- Add SEC and AKShare news adapters behind the `NewsItem` contract.
- Add EODHD, Twelve Data, and AKShare market-data adapters.
- Expand risk theme taxonomy and event classification rules.
- Add broker/export importers under `src/portfolio_input.py` or a future `src/importers/` package.
- Add scheduled daily runs.
- Add more external channel adapters under `src/channels/`.
