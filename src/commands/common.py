from __future__ import annotations

import argparse
from pathlib import Path

from ..agent_runtime import AgentResponse


def portfolio_path(args: argparse.Namespace) -> Path | None:
    return Path(args.portfolio).resolve() if getattr(args, "portfolio", None) else None


def print_agent_response(response: AgentResponse) -> None:
    print(response.text)
    if response.audit_id:
        print(f"\nAudit run: {response.audit_id}")


def prompt_text(label: str, current: str = "", secret: bool = False) -> str:
    shown = "set" if secret and current else current
    suffix = f" [{shown}]" if shown else ""
    visibility = " (paste visible)" if secret else ""
    value = input(f"{label}{visibility}{suffix}: ")
    return value.strip() or current


def prompt_float(label: str, current: float = 0.0) -> float:
    while True:
        raw = input(f"{label} [{current}]: ").strip()
        if not raw:
            return current
        try:
            return float(raw.replace(",", ""))
        except ValueError:
            print("Please enter a number.")


def parse_key_value_pairs(items: list[str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"Expected key=value, got: {item}")
        key, value = item.split("=", 1)
        result[key] = value
    return result

