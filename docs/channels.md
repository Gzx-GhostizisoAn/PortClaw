# Channel Strategy

PortClaw follows the same broad pattern used by local agent systems with messaging gateways:

```text
Platform message
  -> channel adapter
  -> normalized local message
  -> agent runtime
  -> normalized local reply
  -> channel adapter
  -> platform reply
```

The agent runtime should not know whether a message came from CLI, Telegram, WeChat, QQ, WhatsApp, Discord, or Slack. It should only receive a normalized message object.

## Implemented Channels

- `cli`: interactive terminal chat.
- `jsonl`: local inbox/outbox files for gateway-style testing.
- `telegram`: Telegram Bot API polling adapter.

See [channel_runtime.md](channel_runtime.md) for the adapter contract and gateway loop.

## Planned Channels

- `discord`: useful for group workflows and bot commands.
- `slack`: useful for team or workspace deployment.
- `whatsapp`: possible through bridges, but operational stability and account risk need careful review.
- `wechat`: possible through WeCom, official accounts, or bridge tooling, but the exact path depends on account type and platform constraints.
- `qq`: possible through third-party bot frameworks, but it needs extra attention to stability and platform policy.

## Configuration Shape

Each channel uses:

```json
{
  "channel_id": "telegram_personal",
  "channel_type": "telegram",
  "enabled": true,
  "credentials": {
    "bot_token": "..."
  },
  "options": {
    "mode": "polling"
  }
}
```

## Run Local JSONL Gateway

```bash
python agent.py message --text "daily risk brief"
python agent.py gateway --channel local_jsonl --once
tail -n 1 messages/outbox.jsonl
```

## Run Telegram Gateway

Create a Telegram bot through BotFather, then configure the token locally:

```bash
python agent.py configure-channel --channel-id telegram_personal --channel-type telegram --credential bot_token="YOUR_TELEGRAM_BOT_TOKEN" --option timeout=20
python agent.py gateway --channel telegram_personal
```

Do not commit `config/local_config.json`; it contains the bot token.

## Privacy Rule

For now, no external channel should receive raw private portfolio data. The adapter sends user text to the local agent, and the agent returns a report generated from the audited `DailyBrief`.
