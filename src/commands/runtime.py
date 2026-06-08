from __future__ import annotations

import argparse

from ..agent_runtime import LocalFinanceAgent
from .common import portfolio_path, print_agent_response


def cmd_status(_: argparse.Namespace) -> None:
    print(LocalFinanceAgent().status())


def cmd_daily(args: argparse.Namespace) -> None:
    path = portfolio_path(args)
    response = LocalFinanceAgent().run_daily(path) if path else LocalFinanceAgent().run_daily()
    print_agent_response(response)


def cmd_ask(args: argparse.Namespace) -> None:
    question = " ".join(args.question).strip()
    if not question:
        raise SystemExit("Question is required.")
    path = portfolio_path(args)
    response = LocalFinanceAgent().answer(question, path) if path else LocalFinanceAgent().answer(question)
    print_agent_response(response)


def cmd_portfolio(args: argparse.Namespace) -> None:
    path = portfolio_path(args)
    text = LocalFinanceAgent().explain_portfolio_input(path) if path else LocalFinanceAgent().explain_portfolio_input()
    print(text)


def cmd_chat(_: argparse.Namespace) -> None:
    agent = LocalFinanceAgent()
    print("PortClaw CLI chat. Type 'help' for commands, 'exit' to quit.")
    while True:
        try:
            message = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if message.lower() in {"exit", "quit", "q"}:
            break
        print_agent_response(agent.handle_message(message))


def register_runtime_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    status_parser = subparsers.add_parser("status", help="show local runtime status")
    status_parser.set_defaults(func=cmd_status)

    daily_parser = subparsers.add_parser("daily", aliases=["run"], help="run the daily portfolio agent pipeline")
    daily_parser.add_argument("--portfolio", help="path to a local portfolio JSON file")
    daily_parser.set_defaults(func=cmd_daily)

    chat_parser = subparsers.add_parser("chat", help="start interactive CLI chat")
    chat_parser.set_defaults(func=cmd_chat)

    ask_parser = subparsers.add_parser("ask", aliases=["a"], help="ask one free-form question")
    ask_parser.add_argument("question", nargs="+")
    ask_parser.add_argument("--portfolio", help="path to a local portfolio JSON file")
    ask_parser.set_defaults(func=cmd_ask)

    portfolio_parser = subparsers.add_parser("portfolio", aliases=["p"], help="explain current local holdings input")
    portfolio_parser.add_argument("--portfolio", help="path to a local portfolio JSON file")
    portfolio_parser.set_defaults(func=cmd_portfolio)
