from __future__ import annotations

import argparse
import sys

from .commands.channel_commands import register_channel_commands
from .commands.configuration import register_configuration_commands
from .commands.holdings import register_holding_commands
from .commands.menu import register_menu_command
from .commands.runtime import register_runtime_commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PortClaw local CLI")
    subparsers = parser.add_subparsers(required=True)

    register_configuration_commands(subparsers)
    register_runtime_commands(subparsers)
    register_holding_commands(subparsers)
    register_channel_commands(subparsers)
    register_menu_command(subparsers)

    return parser


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
