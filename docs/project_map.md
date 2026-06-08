# Project Map

PortClaw is organized as a local agent runtime rather than a web app.

## Runtime Entry

- `agent.py`: thin executable entrypoint.
- `src/cli.py`: argparse parser registration.
- `src/commands/`: user-facing command implementations, including the interactive menu UI in `src/commands/menu.py`.

## Runtime Core

- `src/agent_runtime.py`: routes CLI/chat messages into daily runs, question answering, status, and portfolio explanations.
- `src/pipeline.py`: orchestration layer that wires data, analytics, intelligence, and reporting inputs into a `DailyBrief`.
- `src/audit.py`: saves briefs, LLM input, LLM output, and run metadata locally.

## Data Layer

- `src/data/news.py`: fetches news, normalizes `NewsItem` objects, classifies `NewsEvent` objects, and calculates portfolio-weighted `NewsImpact`.
- `src/data/market_data/`: market provider contract, provider routing, Yahoo adapter, and market-history normalization.
- `src/portfolio_input.py`: beginner-friendly holdings wizard and CSV import.
- `src/ledger/portfolio_loader.py`: portfolio ledger loading, market-price enrichment, and asset metric creation.

## Analytics Layer

- `src/analytics/metrics.py`: portfolio-level metrics.
- `src/analytics/exposures.py`: sector/currency exposures and basic stress scenarios.
- `src/analytics/signals.py`: raw `Signal` generation with structured evidence.

## Intelligence Layer

- `src/intelligence/risk_theme_engine.py`: maps metrics, raw signals, and news impacts into ranked `RiskTheme` objects.

## Reporting Layer

- `src/reporting/report_generator.py`: turns structured `DailyBrief` objects into local template reports or OpenAI-compatible LLM reports.

## Shared Models And Config

- `src/schemas.py`: shared Pydantic schemas for assets, portfolios, metrics, signals, news, themes, and briefs.
- `src/config.py`: local configuration schema, provider metadata, and config loading/saving.

## Messaging

- `src/message_chat.py`: local JSONL message helpers.
- `src/channel_runner.py`: channel adapter factory and processing loop.
- `src/channels/base.py`: normalized message/reply contract.
- `src/channels/jsonl.py`: local inbox/outbox gateway.
- `src/channels/telegram.py`: Telegram Bot API polling adapter.

## Docs

- `docs/architecture.md`: layered system architecture.
- `docs/daily_pipeline.md`: daily analysis flow.
- `docs/news_layer.md`: news collection, event classification, and impact scoring.
- `docs/input_layer.md`: holdings input model and commands.
- `docs/holding_input_strategy.md`: local-first holding input rationale.
- `docs/channel_runtime.md`: channel adapter contract and gateway loop.
- `docs/channels.md`: channel strategy.
- `docs/local_deployment.md`: local setup and usage.
- `docs/open_source.md`: publishing checklist.

## Extension Points

- Add market-data providers in `src/data/market_data/`.
- Add news sources in `src/data/news.py` or split them into `src/data/news_sources/` as the layer grows.
- Add broker or statement importers near `src/portfolio_input.py`, or split them into `src/importers/`.
- Add message platforms in `src/channels/`.
- Add new signal packs in `src/analytics/signals.py`, or split them into `src/analytics/signal_packs/`.
- Add new risk themes or scoring components in `src/intelligence/risk_theme_engine.py`.
