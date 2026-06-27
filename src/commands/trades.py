from __future__ import annotations

import argparse
from pathlib import Path

from ..portfolio_input import LOCAL_PORTFOLIO_PATH
from ..trade_input import (
    TRADE_LOG_PATH,
    TRADE_TEMPLATE_PATH,
    apply_trades_to_portfolio,
    import_trades_from_csv,
    read_recent_trade_log,
    write_trade_csv_template,
)


def cmd_trade_template(args: argparse.Namespace) -> None:
    output_path = Path(args.output).resolve() if args.output else TRADE_TEMPLATE_PATH
    saved = write_trade_csv_template(output_path)
    print(f"Trade CSV template written: {saved}")
    print("Fill this file with buy/sell rows, then run:")
    print(f"python agent.py import-trades --csv \"{saved}\"")


def cmd_import_trades(args: argparse.Namespace) -> None:
    input_path = Path(args.csv).resolve()
    trades = import_trades_from_csv(input_path)
    portfolio_path = Path(args.portfolio).resolve() if args.portfolio else None
    output_path = Path(args.output).resolve() if args.output else None
    log_path = Path(args.log).resolve() if args.log else TRADE_LOG_PATH
    result = apply_trades_to_portfolio(
        trades=trades,
        portfolio_path=portfolio_path,
        output_path=output_path or LOCAL_PORTFOLIO_PATH,
        log_path=log_path,
    )
    print(f"Imported trades: {result.trades_applied} (buy={result.buys}, sell={result.sells})")
    print(f"Realized P&L from imported sells: {result.realized_pnl:.2f}")
    print(f"Cash after sync: {result.cash_after:.2f}")
    print(f"Positions after sync: {result.positions_after}")
    print(f"Updated holdings: {result.portfolio_path}")
    print(f"Trade behavior log: {result.log_path}")
    print("Next: run `python agent.py portfolio` or `python agent.py daily`.")


def cmd_trade_log(args: argparse.Namespace) -> None:
    log_path = Path(args.log).resolve() if args.log else TRADE_LOG_PATH
    entries = read_recent_trade_log(log_path, limit=int(args.limit))
    if not entries:
        print(f"No trade log entries found at {log_path}")
        return
    print(f"Recent trade behavior log: {log_path}")
    for index, entry in enumerate(entries, start=1):
        trade = entry.get("trade", {})
        print(
            f"{index}. {entry.get('recorded_at')} | {trade.get('side')} {trade.get('symbol')} "
            f"qty={trade.get('quantity')} price={trade.get('price')} "
            f"realized_pnl={entry.get('realized_pnl', 0.0):.2f} "
            f"qty_after={entry.get('position_quantity_after')}"
        )


def register_trade_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    template_parser = subparsers.add_parser("trade-template", help="write a CSV trade import template")
    template_parser.add_argument("--output", help="CSV output path")
    template_parser.set_defaults(func=cmd_trade_template)

    import_parser = subparsers.add_parser("import-trades", help="import buy/sell trades and sync holdings")
    import_parser.add_argument("--csv", required=True, help="CSV file path")
    import_parser.add_argument("--portfolio", help="source portfolio JSON path; default uses local portfolio if present")
    import_parser.add_argument("--output", help="where to save updated holdings JSON")
    import_parser.add_argument("--log", help="where to append the trade behavior JSONL log")
    import_parser.set_defaults(func=cmd_import_trades)

    log_parser = subparsers.add_parser("trade-log", help="show recent local trade behavior log entries")
    log_parser.add_argument("--log", help="trade behavior JSONL path")
    log_parser.add_argument("--limit", default=20, help="number of recent entries to show")
    log_parser.set_defaults(func=cmd_trade_log)
