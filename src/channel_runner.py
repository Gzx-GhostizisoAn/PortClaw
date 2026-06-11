from __future__ import annotations

import sys
import time
from typing import Iterable

from .agent_runtime import LocalFinanceAgent
from .channels.base import ChannelMessage, ChannelReply
from .channels.jsonl import JsonlChannelAdapter
from .channels.telegram import TelegramChannelAdapter
from .config import AgentConfig, ChannelConfig, load_config


SUPPORTED_GATEWAY_TYPES = {"jsonl", "telegram"}


def build_adapter(config: ChannelConfig):
    if config.channel_type == "jsonl":
        return JsonlChannelAdapter(config)
    if config.channel_type == "telegram":
        return TelegramChannelAdapter(config)
    raise ValueError(f"Unsupported channel type: {config.channel_type}")


def iter_enabled_adapters(config: AgentConfig, channel_id: str | None = None):
    for channel in config.channels:
        if not channel.enabled:
            continue
        if channel.channel_type == "cli":
            continue
        if channel_id and channel.channel_id != channel_id:
            continue
        if channel.channel_type not in SUPPORTED_GATEWAY_TYPES:
            print(
                f"Skipping channel {channel.channel_id}: {channel.channel_type} adapter is not implemented yet.",
                file=sys.stderr,
            )
            continue
        yield build_adapter(channel)


def process_messages(messages: Iterable[ChannelMessage], adapter, agent: LocalFinanceAgent) -> int:
    count = 0
    for message in messages:
        response = agent.handle_message(message.text)
        adapter.send(
            ChannelReply(
                message_id=message.message_id,
                channel_id=message.channel_id,
                channel_type=message.channel_type,
                recipient_id=message.sender_id,
                text=response.text,
                audit_id=response.audit_id,
                metadata={"handled_by": response.handled_by},
            )
        )
        count += 1
    return count


def run_once(channel_id: str | None = None) -> int:
    config = load_config()
    agent = LocalFinanceAgent(config)
    total = 0
    for adapter in iter_enabled_adapters(config, channel_id):
        total += process_messages(adapter.receive(), adapter, agent)
    return total


def run_forever(channel_id: str | None = None, interval: float = 5.0) -> None:
    while True:
        count = run_once(channel_id)
        if count:
            print(f"Processed messages: {count}")
        time.sleep(interval)
