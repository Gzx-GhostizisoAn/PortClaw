from __future__ import annotations

import argparse
from pathlib import Path

from ..portfolio_input import (
    CSV_TEMPLATE_PATH,
    LOCAL_PORTFOLIO_PATH,
    build_portfolio,
    import_positions_from_csv,
    normalize_position,
    save_portfolio,
    write_csv_template,
)
from .common import prompt_float, prompt_text


def cmd_holdings_wizard(args: argparse.Namespace) -> None:
    print("Holdings setup")
    print("This creates a private local file: data/portfolio.local.json")
    print("You can press Enter for optional text fields.")
    print("Commands at the symbol prompt: save/done, cancel/exit, list, remove [number].\n")

    user_id = prompt_text("User id", "local_user")
    base_currency = prompt_text("Base currency", "USD").upper()
    cash = prompt_float("Cash balance", 0.0)
    positions = []

    while True:
        symbol = input("\nSymbol / ticker, or command: ").strip()
        command = symbol.lower()
        if command in {"done", "d", "finish", "save", "s"}:
            break
        if command in {"cancel", "exit", "quit", "q"}:
            print("Canceled. Nothing was saved.")
            return
        if command == "list":
            _print_positions(positions)
            continue
        if command.startswith("remove"):
            _remove_position(positions, command)
            continue
        if not symbol:
            print("Symbol is required.")
            continue
        name = prompt_text("Name", symbol.upper())
        sector = prompt_text("Sector", "Unknown")
        quantity = prompt_float("Quantity", 0.0)
        average_cost = prompt_float("Average cost", 0.0)
        market_price = prompt_float("Latest/market price", average_cost)
        try:
            positions.append(
                normalize_position(
                    {
                        "symbol": symbol,
                        "name": name,
                        "sector": sector,
                        "quantity": quantity,
                        "average_cost": average_cost,
                        "market_price": market_price,
                    }
                )
            )
        except ValueError as exc:
            print(f"Skipped invalid position: {exc}")
            continue
        print(f"Added {positions[-1]['symbol']}. Type save when finished, or enter another symbol.")

    if not positions:
        raise SystemExit("No positions entered. Nothing was saved.")

    data = build_portfolio(positions=positions, cash=cash, user_id=user_id, base_currency=base_currency)
    output_path = Path(args.output).resolve() if args.output else LOCAL_PORTFOLIO_PATH
    _print_positions(positions)
    confirm = input(f"\nSave {len(positions)} position(s) to {output_path}? [Y/n]: ").strip().lower()
    if confirm == "n":
        print("Canceled. Nothing was saved.")
        return
    saved = save_portfolio(data, output_path)
    print(f"\nSaved holdings: {saved}")
    print("Next: run `python agent.py portfolio` or `python agent.py daily`.")


def _print_positions(positions: list[dict[str, object]]) -> None:
    if not positions:
        print("No positions entered yet.")
        return
    print("\nPositions entered:")
    for index, item in enumerate(positions, start=1):
        print(
            f"{index}. {item['symbol']} | {item['name']} | {item['sector']} | "
            f"qty={item['quantity']} | cost={item['average_cost']} | price={item['market_price']}"
        )


def _remove_position(positions: list[dict[str, object]], command: str) -> None:
    if not positions:
        print("No positions to remove.")
        return
    parts = command.split()
    if len(parts) == 1:
        removed = positions.pop()
        print(f"Removed {removed['symbol']}.")
        return
    if len(parts) != 2 or not parts[1].isdigit():
        print("Use `remove` for the last position, or `remove 2` for a specific row.")
        return
    index = int(parts[1])
    if index < 1 or index > len(positions):
        print(f"Position number must be between 1 and {len(positions)}.")
        return
    removed = positions.pop(index - 1)
    print(f"Removed {removed['symbol']}.")


def cmd_import_holdings(args: argparse.Namespace) -> None:
    input_path = Path(args.csv).resolve()
    positions = import_positions_from_csv(input_path)
    data = build_portfolio(
        positions=positions,
        cash=float(args.cash or 0.0),
        user_id=args.user_id,
        base_currency=args.base_currency.upper(),
    )
    output_path = Path(args.output).resolve() if args.output else LOCAL_PORTFOLIO_PATH
    saved = save_portfolio(data, output_path)
    print(f"Imported positions: {len(positions)}")
    print(f"Saved holdings: {saved}")
    print("Next: run `python agent.py portfolio` or `python agent.py daily`.")


def cmd_portfolio_template(args: argparse.Namespace) -> None:
    output_path = Path(args.output).resolve() if args.output else CSV_TEMPLATE_PATH
    saved = write_csv_template(output_path)
    print(f"CSV template written: {saved}")
    print("Fill this file, then run:")
    print(f"python agent.py import-holdings --csv \"{saved}\"")


def register_holding_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    holdings_parser = subparsers.add_parser("holdings", aliases=["hld"], help="interactive holdings setup")
    holdings_parser.add_argument("--output", help="where to save holdings JSON")
    holdings_parser.set_defaults(func=cmd_holdings_wizard)

    import_holdings_parser = subparsers.add_parser("import-holdings", aliases=["import"], help="import holdings from CSV")
    import_holdings_parser.add_argument("--csv", required=True, help="CSV file path")
    import_holdings_parser.add_argument("--cash", default=0.0, help="cash balance")
    import_holdings_parser.add_argument("--user-id", default="local_user")
    import_holdings_parser.add_argument("--base-currency", default="USD")
    import_holdings_parser.add_argument("--output", help="where to save holdings JSON")
    import_holdings_parser.set_defaults(func=cmd_import_holdings)

    template_parser = subparsers.add_parser("portfolio-template", aliases=["template"], help="write a CSV holdings template")
    template_parser.add_argument("--output", help="CSV output path")
    template_parser.set_defaults(func=cmd_portfolio_template)
