from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .config import PROJECT_ROOT


LOCAL_PORTFOLIO_PATH = PROJECT_ROOT / "data" / "portfolio.local.json"
EXAMPLE_PORTFOLIO_PATH = PROJECT_ROOT / "data" / "portfolio.example.json"
CSV_TEMPLATE_PATH = PROJECT_ROOT / "data" / "portfolio_template.csv"

FIELD_ALIASES = {
    "symbol": ["symbol", "ticker", "code", "证券代码", "股票代码", "代码"],
    "name": ["name", "asset_name", "证券名称", "股票名称", "名称"],
    "sector": ["sector", "industry", "行业", "板块"],
    "quantity": ["quantity", "qty", "shares", "持仓数量", "数量", "股票余额", "证券余额"],
    "average_cost": ["average_cost", "avg_cost", "cost", "成本价", "持仓成本", "成本"],
}


def default_portfolio_path() -> Path:
    return LOCAL_PORTFOLIO_PATH if LOCAL_PORTFOLIO_PATH.exists() else EXAMPLE_PORTFOLIO_PATH


def save_portfolio(data: Dict[str, Any], path: Path = LOCAL_PORTFOLIO_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_portfolio(
    positions: List[Dict[str, Any]],
    cash: float = 0.0,
    user_id: str = "local_user",
    base_currency: str = "USD",
    watchlist: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    return {
        "user_id": user_id,
        "base_currency": base_currency,
        "cash": cash,
        "positions": positions,
        "watchlist": watchlist or [],
    }


def normalize_position(raw: Dict[str, Any]) -> Dict[str, Any]:
    symbol = str(raw.get("symbol", "")).strip().upper()
    if not symbol:
        raise ValueError("symbol is required")
    quantity = _to_float(raw.get("quantity"), "quantity")
    average_cost = _to_float(raw.get("average_cost"), "average_cost")
    return {
        "symbol": symbol,
        "name": str(raw.get("name", "")).strip() or symbol,
        "sector": str(raw.get("sector", "")).strip() or "Unknown",
        "quantity": quantity,
        "average_cost": average_cost,
    }


def import_positions_from_csv(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            raise ValueError("CSV header is missing")
        field_map = _build_field_map(reader.fieldnames)
        positions = []
        for row in reader:
            normalized = {
                target: row.get(source, "")
                for target, source in field_map.items()
                if source
            }
            if not any(str(value).strip() for value in normalized.values()):
                continue
            positions.append(normalize_position(normalized))
    if not positions:
        raise ValueError("No valid positions found in CSV")
    return positions


def write_csv_template(path: Path = CSV_TEMPLATE_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        ["symbol", "name", "sector", "quantity", "average_cost"],
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerows(rows)
    return path


def _build_field_map(headers: Iterable[str]) -> Dict[str, str]:
    normalized_headers = {header.strip().lower(): header for header in headers}
    output: Dict[str, str] = {}
    for target, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            key = alias.strip().lower()
            if key in normalized_headers:
                output[target] = normalized_headers[key]
                break
    missing = [field for field in ["symbol", "quantity", "average_cost"] if field not in output]
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")
    return output


def _to_float(value: Any, label: str) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number") from exc
