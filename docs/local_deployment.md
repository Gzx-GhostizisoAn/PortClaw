# Local Deployment

PortClaw is a local desktop agent. The normal user entrypoint on macOS is a Finder-launchable `PortClaw.app`; Python commands remain available for development and debugging.

## 1. Install Dependencies

```bash
cd PortClaw
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Build The macOS App

```bash
scripts/build_macos_app.sh
open "$HOME/Applications/PortClaw.app"
```

The builder creates:

- `~/Applications/PortClaw.app`: the double-clickable app bundle.
- `~/Library/Application Support/PortClaw/app`: a clean copy of the runtime source.
- `~/Library/Logs/PortClaw/app.log`: app startup logs.

The generated app bundle and runtime copy exclude local config, private holdings, trade logs, audit runs, message logs, caches, and generated outputs.

To build a standalone app that embeds Python and dependencies:

```bash
scripts/build_pyinstaller_app.sh
open dist/PortClaw.app
```

The standalone app writes local runtime state to `~/Library/Application Support/PortClaw/runtime` and startup logs to `~/Library/Logs/PortClaw/pyinstaller-app.log`.

## 3. Create Local Config

```bash
python agent.py init
python agent.py setup
```

You can configure keys in either `config/local_config.json` or `.env`.

Supported LLM providers:

- `local_template`: no API key, deterministic local report template.
- `qwen`: requires `QWEN_API_KEY`, or a configured key in `local_config.json`.
- `openai`: requires `OPENAI_API_KEY`, or a configured key in `local_config.json`.
- `deepseek`: requires `DEEPSEEK_API_KEY`, or a configured key in `local_config.json`.
- `openai_compatible`: requires an API key, model name, and custom `base_url`.

List model presets:

```bash
python agent.py models
python agent.py data-sources
```

Configure provider, model, key, and base URL:

```bash
python agent.py configure --llm-provider qwen --llm-model qwen-max --llm-api-key "YOUR_QWEN_KEY" --llm-base-url "https://dashscope.aliyuncs.com/compatible-mode/v1"
python agent.py configure --llm-provider deepseek --llm-model deepseek-v4-flash --llm-api-key "YOUR_DEEPSEEK_KEY"
```

Market data providers are represented in config, with `demo` as the default local provider. New adapters can be added under the same contract.

List market data providers:

```bash
python agent.py data-sources
```

Free or public source:

```bash
python agent.py configure --market-provider yahoo
python agent.py configure --market-provider akshare
python agent.py configure --market-provider efinance
python agent.py configure --market-provider ccxt
```

Credentialed source:

```bash
python agent.py configure --market-provider eodhd --market-api-key "YOUR_EODHD_KEY"
python agent.py configure --market-provider fred --market-api-key "YOUR_FRED_KEY"
python agent.py configure --market-provider fmp --market-api-key "YOUR_FMP_KEY"
python agent.py configure --market-provider tushare --market-api-key "YOUR_TUSHARE_TOKEN"
python agent.py configure --market-provider alpha_vantage --market-api-key "YOUR_ALPHA_VANTAGE_KEY"
python agent.py configure --market-provider rqdata --market-api-key "USERNAME:PASSWORD_OR_LICENSE"
```

Provider credential notes:

- `yahoo`, `akshare`, and `efinance` are public/free Python-library style sources and do not use API keys in PortClaw config.
- `ccxt` public market data usually does not require a key, but private exchange account or trading methods require exchange-specific credentials.
- `fred`, `fmp`, `tushare`, `alpha_vantage`, `rqdata`, `eodhd`, and `twelve_data` require keys, tokens, or account/license credentials.
- The implemented Tushare adapter currently fetches China-market daily history for Tushare `ts_code` symbols such as `600519.SH`, `000001.SZ`, or plain six-digit A-share codes.

## 4. Run CLI Agent

```bash
python agent.py status
python agent.py holdings
python agent.py portfolio
python agent.py daily
python agent.py chat
```

For CSV input:

```bash
python agent.py portfolio-template
python agent.py import-holdings --csv data/portfolio_template.csv
```

## 5. Run Message Chat

The message channel is a local JSONL inbox/outbox. It is useful for testing a messaging-gateway style interface before integrating Telegram, Discord, email, or another channel.

```bash
python agent.py message --text "daily risk brief"
python agent.py gateway --channel local_jsonl --once
tail -n 1 messages/outbox.jsonl
```

Outputs are written to:

```text
messages/outbox.jsonl
```

## 6. Configure Channels

```bash
python agent.py channels
python agent.py configure-channel --channel-id telegram_personal --channel-type telegram --credential bot_token="YOUR_BOT_TOKEN" --option mode=polling
```

PortClaw stores channel configuration locally and supports local JSONL plus Telegram Bot API polling. Other platforms can be added by implementing the adapter contract in `src/channels/base.py`.

## 7. Audit Trail

Every daily run stores:

- `daily_brief.json`
- `llm_input.json`
- `llm_output.txt`

under `audit_runs/`.
