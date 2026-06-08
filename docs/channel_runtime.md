# Channel Runtime

The channel runtime follows a model/tool/channel separation similar to local agent frameworks.

```text
External platform
  -> ChannelAdapter.receive()
  -> ChannelMessage
  -> PortClaw runtime
  -> ChannelReply
  -> ChannelAdapter.send()
```

The agent runtime does not depend on Telegram, JSONL, or future platforms. It only sees normalized `ChannelMessage` objects.

## Core Files

- `src/channels/base.py`: normalized message and reply schemas.
- `src/channels/jsonl.py`: local inbox/outbox adapter.
- `src/channels/telegram.py`: Telegram Bot API polling adapter.
- `src/channel_runner.py`: adapter factory and gateway loop.

## Local JSONL Gateway

```bash
python agent.py message --text "daily risk brief"
python agent.py gateway --channel local_jsonl --once
tail -n 1 messages/outbox.jsonl
```

## Telegram Gateway

1. Create a Telegram bot with BotFather.
2. Configure the bot token locally.
3. Start the gateway.

```bash
python agent.py configure-channel --channel-id telegram_personal --channel-type telegram --credential bot_token="YOUR_TELEGRAM_BOT_TOKEN" --option timeout=20
python agent.py gateway --channel telegram_personal
```

Do not commit `config/local_config.json`; it contains channel credentials.

## Adding A New Channel

1. Create `src/channels/<platform>.py`.
2. Implement `receive()` to return `ChannelMessage` objects.
3. Implement `send(reply)` to post `ChannelReply` back to the platform.
4. Register it in `build_adapter()` in `src/channel_runner.py`.
5. Add the channel type to `SUPPORTED_CHANNELS` in `src/config.py`.
