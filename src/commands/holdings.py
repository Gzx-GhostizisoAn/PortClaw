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
    print("You can press Enter for optional text fields. Type 'done' as symbol when finished.\n")

    user_id = prompt_text("User id", "local_user")
    base_currency = prompt_text("Base currency", "USD").upper()
    cash = prompt_float("Cash balance", 0.0)
    positions = []

    while True:
        symbol = input("\nSymbol / ticker (or done): ").strip()
        if symbol.lower() in {"done", "d", "finish", "q", "quit"}:
            break
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

    if not positions:
        raise SystemExit("No positions entered. Nothing was saved.")

    data = build_portfolio(positions=positions, cash=cash, user_id=user_id, base_currency=base_currency)
    output_path = Path(args.output).resolve() if args.output else LOCAL_PORTFOLIO_PATH
    saved = save_portfolio(data, output_path)
    print(f"\nSaved holdings: {saved}")
    print("Next: run `python agent.py portfolio` or `python agent.py daily`.")


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

