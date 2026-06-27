from __future__ import annotations

import argparse
import os
from types import SimpleNamespace

from ..agent_runtime import LocalFinanceAgent
from ..config import available_channels, available_llm_models, available_market_data_providers
from .channel_commands import cmd_channels, cmd_gateway, cmd_message
from .configuration import cmd_config_show, cmd_data_sources, cmd_init, cmd_models, cmd_setup
from .holdings import cmd_holdings_wizard, cmd_import_holdings, cmd_portfolio_template
from .runtime import cmd_chat, cmd_daily, cmd_portfolio, cmd_status
from .trades import cmd_import_trades, cmd_trade_log, cmd_trade_template


RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"


BANNER = r"""
██████╗  ██████╗ ██████╗ ████████╗ ██████╗██╗      █████╗ ██╗    ██╗
██╔══██╗██╔═══██╗██╔══██╗╚══██╔══╝██╔════╝██║     ██╔══██╗██║    ██║
██████╔╝██║   ██║██████╔╝   ██║   ██║     ██║     ███████║██║ █╗ ██║
██╔═══╝ ██║   ██║██╔══██╗   ██║   ██║     ██║     ██╔══██║██║███╗██║
██║     ╚██████╔╝██║  ██║   ██║   ╚██████╗███████╗██║  ██║╚███╔███╔╝
╚═╝      ╚═════╝ ╚═╝  ╚═╝   ╚═╝    ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝
"""


def _ns(**kwargs):
    return SimpleNamespace(**kwargs)


def _clear() -> None:
    if os.environ.get("NO_COLOR"):
        return
    os.system("cls" if os.name == "nt" else "clear")


def _color(text: str, color: str) -> str:
    if os.environ.get("NO_COLOR"):
        return text
    return f"{color}{text}{RESET}"


def _header(title: str) -> None:
    print(_color(BANNER, CYAN))
    print(_color("Local-first portfolio risk intelligence", DIM))
    print(_color(f"\n[{title}]", BOLD))


def _pause() -> None:
    input(_color("\nPress Enter to return...", DIM))


def _choice(prompt: str, options: list[tuple[str, str]]) -> str:
    for key, label in options:
        print(f"  {_color(key, GREEN)}. {label}")
    print(f"  {_color('q', YELLOW)}. Back")
    return input(f"\n{prompt}: ").strip().lower()


def _run_with_pause(func, args=None) -> None:
    try:
        func(args or _ns())
    except SystemExit as exc:
        print(_color(f"\nStopped: {exc}", RED))
    except KeyboardInterrupt:
        print()
    _pause()


def _prompt_path(label: str) -> str | None:
    value = input(f"{label} (press Enter for default): ").strip()
    return value or None


def _initialization_menu() -> None:
    while True:
        _clear()
        _header("Initialization")
        choice = _choice(
            "Select",
            [
                ("1", "Create local config files"),
                ("2", "Run full setup wizard"),
                ("3", "Show runtime status"),
            ],
        )
        if choice == "1":
            _run_with_pause(cmd_init)
        elif choice == "2":
            _run_with_pause(cmd_setup)
        elif choice == "3":
            _run_with_pause(cmd_status)
        elif choice == "q":
            return


def _configuration_menu() -> None:
    while True:
        _clear()
        _header("System Configuration")
        choice = _choice(
            "Select",
            [
                ("1", "Setup wizard: LLM, market data, channels"),
                ("2", "View masked config"),
                ("3", "List LLM providers and models"),
                ("4", "List market data providers"),
                ("5", "List channel types"),
                ("6", "Configure Telegram channel"),
            ],
        )
        if choice == "1":
            _run_with_pause(cmd_setup)
        elif choice == "2":
            _run_with_pause(cmd_config_show)
        elif choice == "3":
            _run_with_pause(cmd_models)
        elif choice == "4":
            _run_with_pause(cmd_data_sources)
        elif choice == "5":
            _run_with_pause(cmd_channels)
        elif choice == "6":
            _configure_telegram()
        elif choice == "q":
            return


def _configure_telegram() -> None:
    _clear()
    _header("Telegram Channel")
    token = input("Bot token: ").strip()
    if not token:
        print("No token entered.")
        _pause()
        return
    from .channel_commands import cmd_configure_channel

    _run_with_pause(
        cmd_configure_channel,
        _ns(
            channel_id="telegram_personal",
            channel_type="telegram",
            credential=[f"bot_token={token}"],
            option=["timeout=20"],
            disabled=False,
        ),
    )


def _supported_content_menu() -> None:
    while True:
        _clear()
        _header("Supported Content")
        print(_color("LLM providers", BOLD))
        for provider, meta in available_llm_models().items():
            models = ", ".join(str(item) for item in meta["models"])
            print(f"  - {provider}: {models}")
        print(_color("\nMarket data providers", BOLD))
        for provider, meta in available_market_data_providers().items():
            print(f"  - {provider}: {meta['label']} [{meta['category']}]")
        print(_color("\nChannels", BOLD))
        for channel_type, meta in available_channels().items():
            print(f"  - {channel_type}: {meta['label']} [{meta['status']}]")
        _pause()
        return


def _analysis_menu() -> None:
    while True:
        _clear()
        _header("Analysis Run")
        choice = _choice(
            "Select",
            [
                ("1", "Run daily portfolio analysis"),
                ("2", "Run daily analysis with custom portfolio JSON"),
                ("3", "Explain current portfolio input"),
                ("4", "Ask a portfolio question"),
                ("5", "Show runtime status"),
            ],
        )
        if choice == "1":
            _run_with_pause(cmd_daily, _ns(portfolio=None))
        elif choice == "2":
            path = _prompt_path("Portfolio JSON path")
            _run_with_pause(cmd_daily, _ns(portfolio=path))
        elif choice == "3":
            _run_with_pause(cmd_portfolio, _ns(portfolio=None))
        elif choice == "4":
            question = input("Question: ").strip()
            if question:
                response = LocalFinanceAgent().answer(question)
                print(response.text)
                if response.audit_id:
                    print(f"\nAudit run: {response.audit_id}")
            _pause()
        elif choice == "5":
            _run_with_pause(cmd_status)
        elif choice == "q":
            return


def _holdings_menu() -> None:
    while True:
        _clear()
        _header("Holdings Input")
        choice = _choice(
            "Select",
            [
                ("1", "Interactive holdings wizard"),
                ("2", "Write CSV template"),
                ("3", "Import holdings from CSV"),
                ("4", "Write trade CSV template"),
                ("5", "Import trades and sync holdings"),
                ("6", "Show recent trade behavior log"),
                ("7", "Explain current holdings file"),
            ],
        )
        if choice == "1":
            output = _prompt_path("Output JSON path")
            _run_with_pause(cmd_holdings_wizard, _ns(output=output))
        elif choice == "2":
            output = _prompt_path("CSV template output path")
            _run_with_pause(cmd_portfolio_template, _ns(output=output))
        elif choice == "3":
            csv_path = input("CSV path: ").strip()
            if csv_path:
                cash = input("Cash balance [0.0]: ").strip() or "0.0"
                currency = input("Base currency [USD]: ").strip() or "USD"
                output = _prompt_path("Output JSON path")
                _run_with_pause(
                    cmd_import_holdings,
                    _ns(csv=csv_path, cash=cash, user_id="local_user", base_currency=currency, output=output),
                )
        elif choice == "4":
            output = _prompt_path("Trade CSV template output path")
            _run_with_pause(cmd_trade_template, _ns(output=output))
        elif choice == "5":
            csv_path = input("Trade CSV path: ").strip()
            if csv_path:
                source = _prompt_path("Source portfolio JSON path")
                output = _prompt_path("Updated holdings output path")
                log = _prompt_path("Trade behavior log path")
                _run_with_pause(cmd_import_trades, _ns(csv=csv_path, portfolio=source, output=output, log=log))
        elif choice == "6":
            log = _prompt_path("Trade behavior log path")
            limit = input("Recent entry limit [20]: ").strip() or "20"
            _run_with_pause(cmd_trade_log, _ns(log=log, limit=limit))
        elif choice == "7":
            _run_with_pause(cmd_portfolio, _ns(portfolio=None))
        elif choice == "q":
            return


def _chat_menu() -> None:
    _clear()
    _header("Chat")
    cmd_chat(_ns())


def _messages_menu() -> None:
    while True:
        _clear()
        _header("Message Gateway")
        choice = _choice(
            "Select",
            [
                ("1", "Queue local JSONL message"),
                ("2", "Process local gateway once"),
                ("3", "Run gateway loop"),
                ("4", "List channel types"),
            ],
        )
        if choice == "1":
            text = input("Message text: ").strip()
            if text:
                _run_with_pause(cmd_message, _ns(text=text))
        elif choice == "2":
            channel = input("Channel id [local_jsonl]: ").strip() or "local_jsonl"
            _run_with_pause(cmd_gateway, _ns(channel=channel, once=True, interval=5.0))
        elif choice == "3":
            channel = input("Channel id [local_jsonl]: ").strip() or "local_jsonl"
            _run_with_pause(cmd_gateway, _ns(channel=channel, once=False, interval=5.0))
        elif choice == "4":
            _run_with_pause(cmd_channels)
        elif choice == "q":
            return


def cmd_menu(_: argparse.Namespace) -> None:
    while True:
        _clear()
        _header("Main Menu")
        choice = _choice(
            "Select a tab",
            [
                ("1", "Initialization"),
                ("2", "System configuration"),
                ("3", "View supported content"),
                ("4", "Analysis run"),
                ("5", "Holdings input"),
                ("6", "Chat interaction"),
                ("7", "Message gateway"),
            ],
        )
        if choice == "1":
            _initialization_menu()
        elif choice == "2":
            _configuration_menu()
        elif choice == "3":
            _supported_content_menu()
        elif choice == "4":
            _analysis_menu()
        elif choice == "5":
            _holdings_menu()
        elif choice == "6":
            _chat_menu()
        elif choice == "7":
            _messages_menu()
        elif choice in {"q", "quit", "exit"}:
            print("Goodbye.")
            return


def register_menu_command(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    menu_parser = subparsers.add_parser("menu", aliases=["ui"], help="start interactive menu UI")
    menu_parser.set_defaults(func=cmd_menu)
