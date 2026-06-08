from __future__ import annotations

import argparse
import json
from datetime import datetime

from ..channel_runner import run_forever, run_once
from ..config import PROJECT_ROOT, ChannelConfig, available_channels, load_config, save_config
from .common import parse_key_value_pairs


def cmd_message(args: argparse.Namespace) -> None:
    config = load_config()
    message_dir = PROJECT_ROOT / config.storage.message_dir
    message_dir.mkdir(parents=True, exist_ok=True)
    inbox = message_dir / "inbox.jsonl"
    item = {"created_at": datetime.utcnow().isoformat(), "text": args.text}
    with inbox.open("a", encoding="utf-8") as file:
        file.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"Queued message: {inbox}")


def cmd_gateway(args: argparse.Namespace) -> None:
    if args.once:
        count = run_once(channel_id=args.channel)
        print(f"Processed messages: {count}")
        return
    print("Channel gateway running. Press Ctrl+C to stop.")
    try:
        run_forever(channel_id=args.channel, interval=args.interval)
    except KeyboardInterrupt:
        print()


def cmd_channels(_: argparse.Namespace) -> None:
    for channel_type, meta in available_channels().items():
        print(f"{channel_type}: {meta['label']} [{meta['status']}]")


def cmd_configure_channel(args: argparse.Namespace) -> None:
    config = load_config()
    existing = next((item for item in config.channels if item.channel_id == args.channel_id), None)
    credentials = parse_key_value_pairs(args.credential)
    options = parse_key_value_pairs(args.option)
    if existing:
        existing.channel_type = args.channel_type or existing.channel_type
        existing.enabled = not args.disabled
        existing.credentials.update(credentials)
        existing.options.update(options)
    else:
        if not args.channel_type:
            raise SystemExit("--channel-type is required for new channels")
        config.channels.append(
            ChannelConfig(
                channel_id=args.channel_id,
                channel_type=args.channel_type,
                enabled=not args.disabled,
                credentials=credentials,
                options=options,
            )
        )
    path = save_config(config)
    print(f"Saved channel config: {path}")


def cmd_channel_remove(args: argparse.Namespace) -> None:
    config = load_config()
    before = len(config.channels)
    config.channels = [item for item in config.channels if item.channel_id != args.channel_id]
    path = save_config(config)
    removed = before - len(config.channels)
    print(f"Removed channels: {removed}")
    print(f"Saved config: {path}")


def register_channel_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    channels_parser = subparsers.add_parser("channels", help="list supported channel types")
    channels_parser.set_defaults(func=cmd_channels)

    message_parser = subparsers.add_parser("message", help="append a local message to inbox")
    message_parser.add_argument("--text", required=True)
    message_parser.set_defaults(func=cmd_message)

    gateway_parser = subparsers.add_parser("gateway", aliases=["serve"], help="run external channel gateway")
    gateway_parser.add_argument("--channel", help="specific channel_id to run")
    gateway_parser.add_argument("--once", action="store_true", help="process once and exit")
    gateway_parser.add_argument("--interval", type=float, default=5.0)
    gateway_parser.set_defaults(func=cmd_gateway)

    channel_parser = subparsers.add_parser("configure-channel", help="configure a local or external message channel")
    channel_parser.add_argument("--channel-id", required=True)
    channel_parser.add_argument("--channel-type", choices=list(available_channels().keys()))
    channel_parser.add_argument("--credential", action="append", help="key=value credential entry")
    channel_parser.add_argument("--option", action="append", help="key=value option entry")
    channel_parser.add_argument("--disabled", action="store_true")
    channel_parser.set_defaults(func=cmd_configure_channel)

    channel_remove_parser = subparsers.add_parser("channel-remove", help="remove a channel from local config")
    channel_remove_parser.add_argument("channel_id")
    channel_remove_parser.set_defaults(func=cmd_channel_remove)
