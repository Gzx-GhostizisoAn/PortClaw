from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .config import PROJECT_ROOT
from .portfolio_input import (
    LOCAL_PORTFOLIO_PATH,
    build_portfolio,
    default_portfolio_path,
    normalize_position,
    save_portfolio,
)


TRADE_TEMPLATE_PATH = PROJECT_ROOT / "data" / "trade_template.csv"
TRADE_LOG_PATH = PROJECT_ROOT / "data" / "trades.local.jsonl"

TRADE_FIELD_ALIASES = {
    "side": ["side", "action", "type", "direction", "交易方向", "买卖方向", "买卖", "操作"],
    "symbol": ["symbol", "ticker", "code", "证券代码", "股票代码", "代码"],
    "name": ["name", "asset_name", "company_name", "company", "证券名称", "股票名称", "公司名称", "名称"],
    "sector": ["sector", "industry", "行业", "板块"],
    "quantity": ["quantity", "qty", "shares", "volume", "成交数量", "股数", "数量", "成交股数"],
    "price": ["price", "trade_price", "成交价格", "买入价格", "卖出价格", "价格", "成交价"],
    "fees": ["fees", "fee", "commission", "tax", "交易费用", "手续费", "佣金", "费用"],
    "amount": ["amount", "cash_amount", "dividend", "金额", "现金金额", "分红", "入金", "出金"],
    "traded_at": ["traded_at", "time", "timestamp", "date", "成交时间", "交易时间", "日期", "成交日期"],
    "note": ["note", "memo", "reason", "journal", "备注", "理由", "交易理由"],
}

BUY_VALUES = {"buy", "b", "long", "purchase", "买", "买入", "购入"}
SELL_VALUES = {"sell", "s", "short", "卖", "卖出", "出售"}
DIVIDEND_VALUES = {"dividend", "div", "分红", "股息"}
DEPOSIT_VALUES = {"deposit", "cash_in", "in", "入金", "存入"}
WITHDRAW_VALUES = {"withdraw", "cash_out", "out", "出金", "取出"}
CASH_EVENT_SIDES = {"dividend", "deposit", "withdraw"}


@dataclass
class TradeApplyResult:
    portfolio_path: Path
    log_path: Path
    trades_applied: int
    buys: int
    sells: int
    realized_pnl: float
    dividends: float
    deposits: float
    withdrawals: float
    cash_after: float
    positions_after: int


def write_trade_csv_template(path: Path = TRADE_TEMPLATE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        ["traded_at", "side", "symbol", "name", "sector", "quantity", "price", "fees", "amount", "note"],
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerows(rows)
    return path


def import_trades_from_csv(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            raise ValueError("CSV header is missing")
        field_map = _build_trade_field_map(reader.fieldnames)
        trades = []
        for row in reader:
            normalized = {
                target: row.get(source, "")
                for target, source in field_map.items()
                if source
            }
            if not any(str(value).strip() for value in normalized.values()):
                continue
            trades.append(normalize_trade(normalized))
    if not trades:
        raise ValueError("No valid trades found in CSV")
    return trades


def normalize_trade(raw: Dict[str, Any]) -> Dict[str, Any]:
    side = _normalize_side(raw.get("side"))
    symbol = str(raw.get("symbol", "")).strip().upper()
    if not symbol and side not in {"deposit", "withdraw"}:
        raise ValueError("symbol is required")
    quantity = 0.0 if side in CASH_EVENT_SIDES else _to_positive_float(raw.get("quantity"), "quantity")
    price = 0.0 if side in CASH_EVENT_SIDES else _to_positive_float(raw.get("price"), "price")
    fees = _to_float(raw.get("fees", 0.0), "fees")
    if fees < 0:
        raise ValueError("fees must be zero or positive")
    amount = _normalize_amount(raw, side, quantity, price, fees)
    traded_at = str(raw.get("traded_at", "")).strip() or datetime.utcnow().isoformat(timespec="seconds")
    return {
        "side": side,
        "symbol": symbol,
        "name": str(raw.get("name", "")).strip() or symbol,
        "sector": str(raw.get("sector", "")).strip() or "Unknown",
        "quantity": quantity,
        "price": price,
        "fees": fees,
        "amount": amount,
        "traded_at": traded_at,
        "note": str(raw.get("note", "")).strip(),
    }


def apply_trades_to_portfolio(
    trades: List[Dict[str, Any]],
    portfolio_path: Path | None = None,
    output_path: Path = LOCAL_PORTFOLIO_PATH,
    log_path: Path = TRADE_LOG_PATH,
) -> TradeApplyResult:
    if not trades:
        raise ValueError("No trades to apply")

    source_path = portfolio_path or default_portfolio_path()
    if not source_path.exists():
        if portfolio_path:
            raise FileNotFoundError(f"Portfolio file does not exist: {source_path}")
        data = build_portfolio(positions=[])
    else:
        data: Dict[str, Any] = json.loads(source_path.read_text(encoding="utf-8"))

    positions = {
        str(item["symbol"]).strip().upper(): normalize_position(item)
        for item in data.get("positions", [])
    }
    cash = float(data.get("cash", 0.0))
    realized_pnl = 0.0
    dividends = 0.0
    deposits = 0.0
    withdrawals = 0.0
    log_entries = []
    applied_at = datetime.utcnow().isoformat(timespec="seconds")

    for raw_trade in trades:
        trade = normalize_trade(raw_trade)
        if trade["side"] in CASH_EVENT_SIDES:
            cash_delta = _cash_event_delta(trade)
            cash += cash_delta
            if trade["side"] == "dividend":
                dividends += cash_delta
            elif trade["side"] == "deposit":
                deposits += cash_delta
            elif trade["side"] == "withdraw":
                withdrawals += abs(cash_delta)
            log_entries.append(
                {
                    "recorded_at": applied_at,
                    "event_type": "cash_event_applied",
                    "source_portfolio": str(source_path),
                    "output_portfolio": str(output_path),
                    "trade": trade,
                    "cash_delta": cash_delta,
                    "realized_pnl": 0.0,
                    "position_quantity_before": None,
                    "position_quantity_after": None,
                    "average_cost_after": None,
                }
            )
            continue
        before = dict(positions.get(trade["symbol"], _empty_position(trade)))
        position, cash_delta, trade_realized_pnl = _apply_trade(before, trade)
        cash += cash_delta
        realized_pnl += trade_realized_pnl
        if position["quantity"] > 0:
            positions[trade["symbol"]] = position
        else:
            positions.pop(trade["symbol"], None)
        log_entries.append(
            {
                "recorded_at": applied_at,
                "event_type": "trade_applied",
                "source_portfolio": str(source_path),
                "output_portfolio": str(output_path),
                "trade": trade,
                "cash_delta": cash_delta,
                "realized_pnl": trade_realized_pnl,
                "position_quantity_before": before.get("quantity", 0.0),
                "position_quantity_after": position.get("quantity", 0.0),
                "average_cost_after": position.get("average_cost", 0.0),
            }
        )

    updated_positions = sorted(positions.values(), key=lambda item: item["symbol"])
    metadata = dict(data.get("metadata", {}))
    previous_trade_ledger = dict(metadata.get("trade_ledger", {}))
    metadata["trade_ledger"] = {
        "last_synced_at": applied_at,
        "source_portfolio": str(source_path),
        "trade_log": str(log_path),
        "last_import_count": len(trades),
        "cumulative_trades_applied": int(previous_trade_ledger.get("cumulative_trades_applied", 0)) + len(trades),
        "last_realized_pnl": realized_pnl,
        "cumulative_realized_pnl": float(previous_trade_ledger.get("cumulative_realized_pnl", 0.0)) + realized_pnl,
        "last_dividends": dividends,
        "cumulative_dividends": float(previous_trade_ledger.get("cumulative_dividends", 0.0)) + dividends,
        "last_deposits": deposits,
        "cumulative_deposits": float(previous_trade_ledger.get("cumulative_deposits", 0.0)) + deposits,
        "last_withdrawals": withdrawals,
        "cumulative_withdrawals": float(previous_trade_ledger.get("cumulative_withdrawals", 0.0)) + withdrawals,
    }
    updated_data = {
        **data,
        "cash": cash,
        "positions": updated_positions,
        "metadata": metadata,
    }
    saved = save_portfolio(updated_data, output_path)
    append_trade_log(log_entries, log_path)

    buys = sum(
        1
        for item in trades
        if str(item.get("side", "")).strip().lower() in BUY_VALUES or item.get("side") == "buy"
    )
    sells = sum(1 for item in trades if normalize_trade(item)["side"] == "sell")
    return TradeApplyResult(
        portfolio_path=saved,
        log_path=log_path,
        trades_applied=len(trades),
        buys=buys,
        sells=sells,
        realized_pnl=realized_pnl,
        dividends=dividends,
        deposits=deposits,
        withdrawals=withdrawals,
        cash_after=cash,
        positions_after=len(updated_positions),
    )


def append_trade_log(entries: Iterable[Dict[str, Any]], path: Path = TRADE_LOG_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        for entry in entries:
            file.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def read_recent_trade_log(path: Path = TRADE_LOG_PATH, limit: int = 20) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    recent = lines[-limit:]
    return [json.loads(line) for line in recent if line.strip()]


def read_trade_log(path: Path = TRADE_LOG_PATH) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def trade_log_summary(path: Path = TRADE_LOG_PATH) -> Dict[str, Any]:
    entries = read_trade_log(path)
    buys = sells = dividends_count = deposits_count = withdrawals_count = 0
    realized_pnl = dividends = deposits = withdrawals = turnover = 0.0
    wins = losses = 0
    for entry in entries:
        trade = entry.get("trade", {})
        side = trade.get("side")
        value = float(trade.get("quantity") or 0.0) * float(trade.get("price") or 0.0)
        if side == "buy":
            buys += 1
            turnover += value
        elif side == "sell":
            sells += 1
            turnover += value
            pnl = float(entry.get("realized_pnl") or 0.0)
            realized_pnl += pnl
            wins += 1 if pnl > 0 else 0
            losses += 1 if pnl < 0 else 0
        elif side == "dividend":
            dividends_count += 1
            dividends += float(entry.get("cash_delta") or 0.0)
        elif side == "deposit":
            deposits_count += 1
            deposits += float(entry.get("cash_delta") or 0.0)
        elif side == "withdraw":
            withdrawals_count += 1
            withdrawals += abs(float(entry.get("cash_delta") or 0.0))
    return {
        "trade_count": len(entries),
        "buys": buys,
        "sells": sells,
        "dividends_count": dividends_count,
        "deposits_count": deposits_count,
        "withdrawals_count": withdrawals_count,
        "realized_pnl": realized_pnl,
        "dividends": dividends,
        "deposits": deposits,
        "withdrawals": withdrawals,
        "turnover": turnover,
        "wins": wins,
        "losses": losses,
        "win_rate": wins / (wins + losses) if wins + losses else None,
    }


def _apply_trade(position: Dict[str, Any], trade: Dict[str, Any]) -> tuple[Dict[str, Any], float, float]:
    quantity = float(position.get("quantity", 0.0))
    average_cost = float(position.get("average_cost", 0.0))
    trade_quantity = float(trade["quantity"])
    trade_price = float(trade["price"])
    fees = float(trade.get("fees", 0.0))

    if trade["side"] == "buy":
        new_quantity = quantity + trade_quantity
        total_cost = quantity * average_cost + trade_quantity * trade_price + fees
        position["quantity"] = new_quantity
        position["average_cost"] = total_cost / new_quantity if new_quantity else 0.0
        position["name"] = trade["name"] or position.get("name") or trade["symbol"]
        position["sector"] = trade["sector"] or position.get("sector") or "Unknown"
        return normalize_position(position), -(trade_quantity * trade_price + fees), 0.0

    if trade_quantity > quantity:
        raise ValueError(f"Sell quantity for {trade['symbol']} exceeds current holding quantity {quantity}")
    realized_pnl = (trade_price - average_cost) * trade_quantity - fees
    new_quantity = quantity - trade_quantity
    position["quantity"] = new_quantity
    position["name"] = trade["name"] or position.get("name") or trade["symbol"]
    position["sector"] = trade["sector"] or position.get("sector") or "Unknown"
    if new_quantity <= 0:
        position["quantity"] = 0.0
        return position, trade_quantity * trade_price - fees, realized_pnl
    return normalize_position(position), trade_quantity * trade_price - fees, realized_pnl


def _cash_event_delta(trade: Dict[str, Any]) -> float:
    amount = float(trade.get("amount") or 0.0)
    fees = float(trade.get("fees") or 0.0)
    if trade["side"] in {"dividend", "deposit"}:
        return amount - fees
    return -(amount + fees)


def _empty_position(trade: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "symbol": trade["symbol"],
        "name": trade["name"],
        "sector": trade["sector"],
        "quantity": 0.0,
        "average_cost": 0.0,
    }


def _build_trade_field_map(headers: Iterable[str]) -> Dict[str, str]:
    normalized_headers = {header.strip().lower(): header for header in headers}
    output: Dict[str, str] = {}
    for target, aliases in TRADE_FIELD_ALIASES.items():
        for alias in aliases:
            key = alias.strip().lower()
            if key in normalized_headers:
                output[target] = normalized_headers[key]
                break
    missing = [field for field in ["side"] if field not in output]
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")
    return output


def _normalize_side(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in BUY_VALUES:
        return "buy"
    if normalized in SELL_VALUES:
        return "sell"
    if normalized in DIVIDEND_VALUES:
        return "dividend"
    if normalized in DEPOSIT_VALUES:
        return "deposit"
    if normalized in WITHDRAW_VALUES:
        return "withdraw"
    raise ValueError("side must be buy/sell/dividend/deposit/withdraw")


def _normalize_amount(raw: Dict[str, Any], side: str, quantity: float, price: float, fees: float) -> float:
    raw_amount = raw.get("amount")
    if side in CASH_EVENT_SIDES:
        amount = _to_positive_float(raw_amount, "amount")
        return amount
    return quantity * price + fees


def _to_positive_float(value: Any, label: str) -> float:
    number = _to_float(value, label)
    if number <= 0:
        raise ValueError(f"{label} must be greater than zero")
    return number


def _to_float(value: Any, label: str) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number") from exc
