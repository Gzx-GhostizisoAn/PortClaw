# Local Deployment

PortClaw is a local agent runtime, not a web product. The first deployment target is a personal machine running Python.

## 1. Install

```bash
cd PortClaw
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Create Local Config

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

Free source:

```bash
python agent.py configure --market-provider yahoo
```

Commercial source:

```bash
python agent.py configure --market-provider eodhd --market-api-key "YOUR_EODHD_KEY"
```

## 3. Run CLI Agent

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

## 4. Run Message Chat

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

## 5. Configure Channels

```bash
python agent.py channels
python agent.py configure-channel --channel-id telegram_personal --channel-type telegram --credential bot_token="YOUR_BOT_TOKEN" --option mode=polling
```

PortClaw stores channel configuration locally and supports local JSONL plus Telegram Bot API polling. Other platforms can be added by implementing the adapter contract in `src/channels/base.py`.

## 6. Audit Trail

Every daily run stores:

- `daily_brief.json`
- `llm_input.json`
- `llm_output.txt`

under `audit_runs/`.
