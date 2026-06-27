from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse
import webbrowser
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from .config import PROJECT_ROOT, available_market_data_providers, config_path, load_config
from .config import (
    AppUIConfig,
    LLMConfig,
    MarketDataConfig,
    NewsConfig,
    available_llm_models,
    normalize_llm_config,
    normalize_market_data_config,
    save_config as persist_config,
)
from .portfolio_input import LOCAL_PORTFOLIO_PATH, build_portfolio, default_portfolio_path, normalize_position, save_portfolio
from .data.market_data import MarketDataClient
from .data.news import NewsFetcher
from .trade_input import TRADE_LOG_PATH, apply_trades_to_portfolio, read_recent_trade_log, read_trade_log, trade_log_summary


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
COMMAND_TIMEOUT_SECONDS = 180
DASHBOARD_HISTORY_CACHE_PATH = PROJECT_ROOT / "data" / "dashboard_history_cache.json"


def _money(value: float | None) -> float | None:
    return round(value, 2) if value is not None and math.isfinite(value) else None


def _pct(value: float | None) -> float | None:
    return round(value, 4) if value is not None and math.isfinite(value) else None


def _normalize_timezone_name(value: str | None) -> str:
    name = (value or "Asia/Shanghai").strip() or "Asia/Shanghai"
    try:
        ZoneInfo(name)
        return name
    except ZoneInfoNotFoundError:
        return "Asia/Shanghai"


def _app_timezone(config: Any | None = None) -> ZoneInfo:
    config = config or load_config()
    return ZoneInfo(_normalize_timezone_name(getattr(config.app, "timezone", "Asia/Shanghai")))


def _local_date(value: Any, tz: ZoneInfo) -> Any:
    parsed = value
    try:
        parsed = parsed.to_pydatetime()
    except AttributeError:
        pass
    if isinstance(parsed, datetime):
        if parsed.tzinfo is not None:
            return parsed.astimezone(tz).date()
        return parsed.date()
    if hasattr(parsed, "date"):
        return parsed.date()
    return parsed


def _timezone_label(name: str) -> str:
    return {
        "Asia/Shanghai": "北京时间",
        "Asia/Hong_Kong": "香港时间",
        "Asia/Tokyo": "东京时间",
        "America/New_York": "美东时间",
        "America/Chicago": "美中时间",
        "America/Denver": "美山时间",
        "America/Los_Angeles": "美西时间",
        "Europe/London": "伦敦时间",
        "Europe/Paris": "巴黎时间",
        "UTC": "UTC",
    }.get(name, name)


def _safe_config() -> dict[str, Any]:
    config = load_config()
    data = config.model_dump(mode="json")
    data.setdefault("_secrets", {})
    data["_secrets"]["llm_api_key_set"] = bool(data.get("llm", {}).get("api_key"))
    data["_secrets"]["market_api_key_set"] = bool(data.get("market_data", {}).get("api_key"))
    if data.get("llm", {}).get("api_key"):
        data["llm"]["api_key"] = "***"
    if data.get("market_data", {}).get("api_key"):
        data["market_data"]["api_key"] = "***"
    for channel in data.get("channels", []):
        for key in list(channel.get("credentials", {}).keys()):
            channel["credentials"][key] = "***"
    return data


def _config_options() -> dict[str, Any]:
    return {
        "llm_models": available_llm_models(),
        "market_providers": available_market_data_providers(),
        "news_sources": {
            "auto": {"label": "Auto", "description": "优先使用当前数据源新闻能力，失败后尝试通用 fallback。"},
            "provider": {"label": "Current Provider", "description": "只使用当前 Market Provider 的新闻能力。"},
            "crawler": {"label": "Web Crawler", "description": "自动识别 A 股/海外股票，A 股用百度新闻，海外用 Yahoo News。"},
        },
        "news_lookbacks": {
            "today": {"label": "今日新闻"},
            "7d": {"label": "七日内新闻"},
            "1m": {"label": "一个月内新闻"},
            "6m": {"label": "半年内新闻"},
        },
        "languages": {
            "zh-CN": {"label": "简体中文"},
            "zh-TW": {"label": "繁體中文"},
            "en": {"label": "English"},
            "ja": {"label": "日本語"},
            "fr": {"label": "Français"},
        },
        "cache_policies": {
            "standard": {"label": "标准缓存", "description": "保留必要运行缓存，只清理临时 Python 缓存。"},
            "lean": {"label": "轻量缓存", "description": "更适合试用机器，优先减少本地缓存占用。"},
            "keep": {"label": "保留缓存", "description": "不自动清理缓存，适合调试。"},
        },
        "timezones": {
            "Asia/Shanghai": {"label": "中国时间 UTC+8"},
            "Asia/Hong_Kong": {"label": "香港时间 UTC+8"},
            "Asia/Tokyo": {"label": "日本时间 UTC+9"},
            "America/New_York": {"label": "美东时间"},
            "America/Chicago": {"label": "美中时间"},
            "America/Denver": {"label": "美山时间"},
            "America/Los_Angeles": {"label": "美西时间"},
            "Europe/London": {"label": "伦敦时间"},
            "Europe/Paris": {"label": "巴黎时间"},
            "UTC": {"label": "UTC"},
        },
    }


def _credential_ready(provider: str, api_key: str, catalog: dict[str, dict[str, object]]) -> bool:
    meta = catalog.get(provider, {})
    return not bool(meta.get("requires_api_key", True)) or bool(api_key)


def _configuration_ready(config: Any) -> bool:
    llm_ready = _credential_ready(config.llm.provider, config.llm.api_key, available_llm_models())
    market_ready = _credential_ready(config.market_data.provider, config.market_data.api_key, available_market_data_providers())
    return llm_ready and market_ready


def _setup_state(config: Any | None = None) -> dict[str, Any]:
    config = config or load_config()
    existing_config_is_ready = config_path().exists() and _configuration_ready(config)
    completed = bool(getattr(config.app, "onboarding_completed", False) or existing_config_is_ready)
    return {
        "completed": completed,
        "required": not completed,
        "config_ready": _configuration_ready(config),
        "config_path": str(config_path()),
    }


def _save_runtime_config(payload: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    llm = payload.get("llm")
    if isinstance(llm, dict):
        provider = str(llm.get("provider") or config.llm.provider)
        model = str(llm.get("model") or "")
        base_url = str(llm.get("base_url") or "")
        api_key = str(llm.get("api_key") or "")
        keep_api_key = bool(llm.get("keep_api_key", True))
        config.llm = normalize_llm_config(
            LLMConfig(
                provider=provider,
                model=model,
                api_key=config.llm.api_key if keep_api_key and not api_key else api_key,
                base_url=base_url,
            )
        )

    market_data = payload.get("market_data")
    if isinstance(market_data, dict):
        provider = str(market_data.get("provider") or config.market_data.provider)
        base_url = str(market_data.get("base_url") or "")
        api_key = str(market_data.get("api_key") or "")
        keep_api_key = bool(market_data.get("keep_api_key", True))
        config.market_data = normalize_market_data_config(
            MarketDataConfig(
                provider=provider,
                api_key=config.market_data.api_key if keep_api_key and not api_key else api_key,
                base_url=base_url,
            )
        )

    news = payload.get("news")
    if isinstance(news, dict):
        provider = str(news.get("provider") or config.news.provider or "auto")
        if provider not in {"auto", "provider", "crawler"}:
            provider = "auto"
        lookback = str(news.get("lookback") or config.news.lookback or "7d")
        if lookback not in {"today", "7d", "1m", "6m"}:
            lookback = "7d"
        config.news = NewsConfig(provider=provider, lookback=lookback)

    app = payload.get("app")
    if isinstance(app, dict):
        language = str(app.get("language") or config.app.language or "zh-CN")
        if language not in {"zh-CN", "zh-TW", "en", "ja", "fr"}:
            language = "zh-CN"
        cache_policy = str(app.get("cache_policy") or config.app.cache_policy or "standard")
        if cache_policy not in {"standard", "lean", "keep"}:
            cache_policy = "standard"
        timezone_name = _normalize_timezone_name(str(app.get("timezone") or config.app.timezone or "Asia/Shanghai"))
        onboarding_completed = bool(config.app.onboarding_completed)
        if bool(app.get("onboarding_completed")) and _configuration_ready(config):
            onboarding_completed = True
        config.app = AppUIConfig(
            language=language,
            onboarding_completed=onboarding_completed,
            cache_policy=cache_policy,
            timezone=timezone_name,
        )

    if bool(payload.get("complete_onboarding")) and _configuration_ready(config):
        config.app.onboarding_completed = True

    path = persist_config(config)
    return {"ok": True, "path": str(path), "config": _safe_config(), "setup": _setup_state(config)}


def _clear_runtime_cache() -> dict[str, Any]:
    removed: list[str] = []
    for directory in PROJECT_ROOT.rglob("__pycache__"):
        if directory.is_dir():
            shutil.rmtree(directory, ignore_errors=True)
            removed.append(str(directory.relative_to(PROJECT_ROOT)))
    for directory_name in (".pytest_cache", ".mypy_cache", ".ruff_cache"):
        directory = PROJECT_ROOT / directory_name
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)
            removed.append(directory_name)
    for pyc in PROJECT_ROOT.rglob("*.pyc"):
        try:
            pyc.unlink()
            removed.append(str(pyc.relative_to(PROJECT_ROOT)))
        except OSError:
            pass
    return {"ok": True, "removed": removed, "count": len(removed)}


def _overview_payload() -> dict[str, Any]:
    return {
        "config": _safe_config(),
        "portfolio": _portfolio_data(),
        "providers": available_market_data_providers(),
        "options": _config_options(),
        "setup": _setup_state(),
        "project_root": str(PROJECT_ROOT),
    }



def _portfolio_data() -> dict[str, Any]:
    path = default_portfolio_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["_source_path"] = str(path)
    data["_is_local"] = path == LOCAL_PORTFOLIO_PATH
    return data


def _dedupe_symbols(positions: list[dict[str, Any]]) -> list[str]:
    symbols = [str(item.get("symbol") or "").strip().upper() for item in positions if item.get("symbol")]
    return sorted({symbol for symbol in symbols if symbol})


def _dashboard_history_cache_key(provider: str, symbols: list[str], period: str, cutoff_date: Any) -> str:
    symbol_part = ",".join(symbols)
    return f"{provider}|{period}|{cutoff_date}|{symbol_part}"


def _history_to_records(history: Any) -> list[dict[str, Any]]:
    if history is None or getattr(history, "empty", True):
        return []
    records: list[dict[str, Any]] = []
    for raw in history.to_dict(orient="records"):
        record: dict[str, Any] = {}
        for key, value in raw.items():
            if key == "date":
                try:
                    value = value.date().isoformat()
                except AttributeError:
                    value = str(value)
            elif hasattr(value, "item"):
                value = value.item()
            if isinstance(value, float) and not math.isfinite(value):
                value = None
            record[key] = value
        records.append(record)
    return records


def _records_to_history(records: list[dict[str, Any]]) -> Any:
    frame = pd.DataFrame(records)
    if frame.empty:
        return frame
    if "date" in frame:
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values("date").reset_index(drop=True)
    return frame


def _read_dashboard_history_cache(cache_key: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(DASHBOARD_HISTORY_CACHE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    entry = payload.get("entries", {}).get(cache_key)
    if not isinstance(entry, dict):
        return None
    histories_payload = entry.get("histories", {})
    if not isinstance(histories_payload, dict):
        return None
    histories = {
        symbol: _records_to_history(records)
        for symbol, records in histories_payload.items()
        if isinstance(records, list)
    }
    errors = entry.get("errors", {})
    return {
        "histories": histories,
        "errors": errors if isinstance(errors, dict) else {},
        "provider": entry.get("provider"),
        "cache": "hit",
        "cache_key": cache_key,
        "cached_at": entry.get("cached_at"),
    }


def _write_dashboard_history_cache(
    cache_key: str,
    *,
    provider: str,
    histories: dict[str, Any],
    errors: dict[str, Any],
) -> str | None:
    if not histories:
        return None
    try:
        payload = json.loads(DASHBOARD_HISTORY_CACHE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        payload = {}
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    cached_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entries[cache_key] = {
        "provider": provider,
        "cached_at": cached_at,
        "histories": {symbol: _history_to_records(history) for symbol, history in histories.items()},
        "errors": errors,
    }
    payload["entries"] = entries
    DASHBOARD_HISTORY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DASHBOARD_HISTORY_CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return cached_at


def _fetch_dashboard_history(positions: list[dict[str, Any]], *, cutoff_date: Any | None = None) -> dict[str, Any]:
    symbols = _dedupe_symbols(positions)
    config = load_config()
    if not symbols:
        return {
            "histories": {},
            "errors": {},
            "provider": config.market_data.provider,
            "cache": "none",
            "cache_key": None,
            "cached_at": None,
        }
    period = "1y"
    cache_key = _dashboard_history_cache_key(config.market_data.provider, symbols, period, cutoff_date or "latest")
    cached = _read_dashboard_history_cache(cache_key)
    if cached is not None:
        cached["provider"] = cached.get("provider") or config.market_data.provider
        return cached

    client = MarketDataClient(config)
    results = client.fetch_many(symbols, period=period)
    histories = {symbol: result.history for symbol, result in results.items() if result.ok}
    errors = {symbol: result.error for symbol, result in results.items() if not result.ok}
    cached_at = _write_dashboard_history_cache(cache_key, provider=config.market_data.provider, histories=histories, errors=errors)
    return {
        "histories": histories,
        "errors": errors,
        "provider": config.market_data.provider,
        "cache": "miss" if cached_at else "disabled",
        "cache_key": cache_key,
        "cached_at": cached_at,
    }


def _history_price_at_or_before(history: Any, target: Any) -> float | None:
    if history is None or getattr(history, "empty", True) or target is None:
        return None
    rows = history[history["date"] <= target]
    if rows.empty:
        return None
    return float(rows["close"].iloc[-1])


def _portfolio_history_stats(
    rows: list[dict[str, Any]],
    histories: dict[str, Any],
    cash: float,
    *,
    today: Any,
    cutoff_date: Any,
    previous_day_date: Any,
    tz: ZoneInfo,
) -> dict[str, Any]:
    dated_values: dict[Any, float] = {}
    static_value = cash + sum(row["market_value"] for row in rows if row["symbol"] not in histories)
    for row in rows:
        history = histories.get(row["symbol"])
        if history is None or getattr(history, "empty", True):
            continue
        for _, point in history.iterrows():
            date = _local_date(point["date"], tz)
            if date > cutoff_date:
                continue
            dated_values[date] = dated_values.get(date, static_value) + row["quantity"] * float(point["close"])

    series = sorted((date, value) for date, value in dated_values.items())
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    ytd_start = today.replace(month=1, day=1)

    def empty_period(status: str = "history_unavailable") -> dict[str, Any]:
        return {"pnl": None, "return": None, "status": status}

    def empty_stats() -> dict[str, Any]:
        return {
            "today": str(today),
            "cutoff_date": str(cutoff_date),
            "previous_day_date": str(previous_day_date),
            "week_start": str(week_start),
            "month_start": str(month_start),
            "ytd_start": str(ytd_start),
            "latest_market_date": None,
            "previous_day": empty_period(),
            "week": empty_period(),
            "month": empty_period(),
            "ytd": empty_period(),
            "calendar_month": str(month_start)[:7],
            "calendar_days": [],
            "week_max_drawdown": None,
            "volatility": None,
            "sharpe_ratio": None,
            "history_points": len(series),
        }

    if len(series) < 2:
        return empty_stats()

    latest_date, latest_value = series[-1]

    daily_changes = []
    previous_date, previous_value = series[0]
    for date, value in series[1:]:
        pnl = value - previous_value
        daily_changes.append(
            {
                "date": str(date),
                "previous_date": str(previous_date),
                "pnl": pnl,
                "return": pnl / previous_value if previous_value else None,
                "total_assets": value,
                "previous_total_assets": previous_value,
            }
        )
        previous_date = date
        previous_value = value

    def value_at_or_before(target: Any) -> float | None:
        if target is None:
            return None
        earlier = [value for date, value in series if date <= target]
        return earlier[-1] if earlier else None

    def period_stats(start: Any) -> dict[str, Any]:
        if latest_date < start:
            return empty_period()
        changes = [
            item
            for item in daily_changes
            if start <= datetime.fromisoformat(item["date"]).date() <= latest_date
        ]
        if not changes:
            return empty_period()
        start_value = float(changes[0]["previous_total_assets"])
        pnl = sum(float(item["pnl"]) for item in changes)
        return {"pnl": pnl, "return": pnl / start_value if start_value else None, "status": "ok"}

    previous_day_changes = [
        item for item in daily_changes if datetime.fromisoformat(item["date"]).date() == previous_day_date
    ]
    previous_day_change = previous_day_changes[-1] if previous_day_changes else None
    previous_day = (
        {
            "pnl": float(previous_day_change["pnl"]),
            "return": previous_day_change["return"],
            "status": "ok",
        }
        if previous_day_change
        else empty_period()
    )

    def period_drawdown(start: Any) -> float | None:
        if latest_date < start:
            return None
        values = [value for date, value in series if start <= date <= cutoff_date]
        if len(values) < 2:
            return None
        running_max = values[0]
        drawdown = 0.0
        for value in values[1:]:
            running_max = max(running_max, value)
            if running_max > 0:
                drawdown = min(drawdown, value / running_max - 1)
        return drawdown

    returns = []
    prev_value = series[0][1]
    for _, value in series[1:]:
        if prev_value > 0:
            returns.append(value / prev_value - 1)
        prev_value = value

    volatility = None
    sharpe = None
    if len(returns) >= 2:
        mean_return = sum(returns) / len(returns)
        variance = sum((item - mean_return) ** 2 for item in returns) / (len(returns) - 1)
        daily_vol = math.sqrt(variance)
        volatility = daily_vol * math.sqrt(252)
        sharpe = (mean_return / daily_vol) * math.sqrt(252) if daily_vol else None

    calendar_days = [
        {
            "date": item["date"],
            "day": datetime.fromisoformat(item["date"]).day,
            "pnl": _money(float(item["pnl"])),
            "return": _pct(item["return"]),
            "total_assets": _money(float(item["total_assets"])),
        }
        for item in daily_changes
        if datetime.fromisoformat(item["date"]).date().year == latest_date.year
        and datetime.fromisoformat(item["date"]).date().month == latest_date.month
    ]

    return {
        "today": str(today),
        "cutoff_date": str(cutoff_date),
        "previous_day_date": str(previous_day_date),
        "week_start": str(week_start),
        "month_start": str(month_start),
        "ytd_start": str(ytd_start),
        "latest_market_date": str(latest_date),
        "previous_day": previous_day,
        "week": period_stats(week_start),
        "month": period_stats(month_start),
        "ytd": period_stats(ytd_start),
        "calendar_month": f"{latest_date.year:04d}-{latest_date.month:02d}",
        "calendar_days": calendar_days,
        "week_max_drawdown": period_drawdown(week_start),
        "volatility": volatility,
        "sharpe_ratio": sharpe,
        "history_points": len(series),
    }


def _normalize_news_lookback(value: str | None) -> str:
    return value if value in {"today", "7d", "1m", "6m"} else "7d"


def _dashboard_news_data(positions: list[dict[str, Any]], lookback: str | None = None) -> dict[str, Any]:
    config = load_config()
    lookback = _normalize_news_lookback(lookback or config.news.lookback)
    fetcher = NewsFetcher(config)
    items = fetcher.fetch_portfolio_news(positions, limit=10, lookback=lookback)
    return {
        "provider": config.market_data.provider,
        "lookback": lookback,
        "status": fetcher.last_status,
        "items": [
            {
                "title": item.title,
                "summary": item.content[:220],
                "source": item.source,
                "timestamp": item.timestamp.isoformat(),
                "symbols": item.symbols,
                "url": item.url,
            }
            for item in items
        ],
    }


def _dashboard_data() -> dict[str, Any]:
    config = load_config()
    tz = _app_timezone(config)
    now = datetime.now(tz)
    today = now.date()
    previous_day_date = today - timedelta(days=1)
    cutoff_date = previous_day_date
    portfolio = _portfolio_data()
    positions = portfolio.get("positions", [])
    history_payload = _fetch_dashboard_history(positions, cutoff_date=cutoff_date)
    histories = history_payload["histories"]
    history_errors = history_payload["errors"]
    cash = float(portfolio.get("cash") or 0.0)
    base_currency = str(portfolio.get("base_currency") or "USD")
    rows = []
    market_value = 0.0
    total_cost = 0.0
    for item in positions:
        symbol = str(item.get("symbol") or "").upper()
        history = histories.get(symbol)
        quantity = float(item.get("quantity") or 0.0)
        latest_history = None
        previous_history = None
        if history is not None and not history.empty:
            usable_points = []
            for _, point in history.iterrows():
                local_day = _local_date(point["date"], tz)
                if local_day <= cutoff_date:
                    usable_points.append((local_day, point))
            if usable_points:
                latest_history = usable_points[-1]
                previous_history = usable_points[-2] if len(usable_points) >= 2 else None
        price = float(latest_history[1]["close"]) if latest_history is not None else float(item.get("average_cost") or 0.0)
        average_cost = float(item.get("average_cost") or 0.0)
        value = quantity * price
        cost = quantity * average_cost
        previous_close = float(previous_history[1]["close"]) if previous_history is not None else None
        row_previous_day = quantity * (price - float(previous_close)) if previous_close is not None else None
        market_value += value
        total_cost += cost
        rows.append(
            {
                "symbol": str(item.get("symbol") or "").upper(),
                "name": item.get("name") or item.get("symbol"),
                "sector": item.get("sector") or "Unknown",
                "quantity": quantity,
                "market_price": price,
                "average_cost": average_cost,
                "market_value": value,
                "cost": cost,
                "unrealized_pnl": value - cost,
                "unrealized_return": (value - cost) / cost if cost else None,
                "daily_pnl": row_previous_day,
                "latest_market_date": str(latest_history[0]) if latest_history is not None else None,
                "history_ok": symbol in histories,
                "history_error": history_errors.get(symbol),
            }
        )

    total_assets = market_value + cash
    for row in rows:
        row["weight"] = row["market_value"] / total_assets if total_assets else 0.0

    allocation_map: dict[str, float] = {}
    for row in rows:
        allocation_map[row["sector"]] = allocation_map.get(row["sector"], 0.0) + row["market_value"]
    if cash:
        allocation_map["Cash"] = allocation_map.get("Cash", 0.0) + cash

    allocation = [
        {"name": name, "value": _money(value), "weight": _pct(value / total_assets if total_assets else 0.0)}
        for name, value in sorted(allocation_map.items(), key=lambda item: item[1], reverse=True)
    ]
    holdings = [
        {
            "symbol": row["symbol"],
            "name": row["name"],
            "sector": row["sector"],
            "value": _money(row["market_value"]),
            "weight": _pct(row["weight"]),
            "unrealized_pnl": _money(row["unrealized_pnl"]),
            "unrealized_return": _pct(row["unrealized_return"]),
        }
        for row in sorted(rows, key=lambda item: item["market_value"], reverse=True)
    ]

    largest_weight = max((row["weight"] for row in rows), default=0.0)
    sector_hhi = sum((item["weight"] or 0.0) ** 2 for item in allocation if item["name"] != "Cash")
    cash_ratio = cash / total_assets if total_assets else 0.0
    total_unrealized = market_value - total_cost
    total_return = total_unrealized / total_cost if total_cost else None
    history_stats = _portfolio_history_stats(
        rows,
        histories,
        cash,
        today=today,
        cutoff_date=cutoff_date,
        previous_day_date=previous_day_date,
        tz=tz,
    )
    previous_day_stats = history_stats["previous_day"]
    week_stats = history_stats["week"]
    month_stats = history_stats["month"]
    ytd_stats = history_stats["ytd"]

    risk_score = min(100.0, largest_weight * 120 + sector_hhi * 55 + (20 if cash_ratio < 0.05 else 0))
    if risk_score >= 68:
        risk_level = "High"
    elif risk_score >= 38:
        risk_level = "Medium"
    else:
        risk_level = "Low"

    exposures = _build_dashboard_exposures(rows, allocation, cash_ratio)
    trade_summary = trade_log_summary(TRADE_LOG_PATH)
    trade_entries = read_trade_log(TRADE_LOG_PATH)
    profile = _build_profile(
        risk_level=risk_level,
        risk_score=risk_score,
        largest_weight=largest_weight,
        cash_ratio=cash_ratio,
        sector_hhi=sector_hhi,
        total_assets=total_assets,
        trade_summary=trade_summary,
        trade_entries=trade_entries,
    )
    alerts = _build_dashboard_alerts(rows, allocation, largest_weight, cash_ratio, risk_level)
    alerts.extend(_build_behavior_alerts(profile))
    optimization = _build_optimization_suggestions(allocation, cash_ratio, largest_weight)
    news = _dashboard_news_data(positions)

    return {
        "as_of": portfolio.get("_source_path"),
        "base_currency": base_currency,
        "metrics": {
            "total_assets": _money(total_assets),
            "market_value": _money(market_value),
            "cash": _money(cash),
            "cash_ratio": _pct(cash_ratio),
            "today_pnl": _money(previous_day_stats["pnl"]),
            "today_return": _pct(previous_day_stats["return"]),
            "week_pnl": _money(week_stats["pnl"]),
            "week_return": _pct(week_stats["return"]),
            "month_pnl": _money(month_stats["pnl"]),
            "month_return": _pct(month_stats["return"]),
            "ytd_pnl": _money(ytd_stats["pnl"]),
            "ytd_return": _pct(ytd_stats["return"]),
            "total_unrealized_pnl": _money(total_unrealized),
            "total_unrealized_return": _pct(total_return),
            "risk_level": risk_level,
            "risk_score": round(risk_score, 1),
            "max_drawdown": _pct(history_stats["week_max_drawdown"]),
            "volatility": _pct(history_stats["volatility"]),
            "sharpe_ratio": _money(history_stats["sharpe_ratio"]),
            "largest_position_weight": _pct(largest_weight),
            "sector_concentration": _pct(sector_hhi),
        },
        "periods": {
            "today": {"pnl": _money(previous_day_stats["pnl"]), "return": _pct(previous_day_stats["return"]), "status": previous_day_stats["status"]},
            "week": {"pnl": _money(week_stats["pnl"]), "return": _pct(week_stats["return"]), "status": week_stats["status"]},
            "month": {"pnl": _money(month_stats["pnl"]), "return": _pct(month_stats["return"]), "status": month_stats["status"]},
            "ytd": {"pnl": _money(ytd_stats["pnl"]), "return": _pct(ytd_stats["return"]), "status": ytd_stats["status"]},
        },
        "time": {
            "timezone": str(getattr(config.app, "timezone", "Asia/Shanghai")),
            "timezone_label": _timezone_label(str(getattr(config.app, "timezone", "Asia/Shanghai"))),
            "now": now.isoformat(timespec="seconds"),
            "local_date": today.isoformat(),
            "local_time": now.strftime("%H:%M"),
            "today": history_stats["today"],
            "cutoff_date": history_stats["cutoff_date"],
            "previous_day_date": history_stats["previous_day_date"],
            "week_start": history_stats["week_start"],
            "month_start": history_stats["month_start"],
            "ytd_start": history_stats["ytd_start"],
            "latest_market_date": history_stats["latest_market_date"],
        },
        "calendar": {
            "month": history_stats["calendar_month"],
            "days": history_stats["calendar_days"],
        },
        "market_history": {
            "provider": history_payload["provider"],
            "ok_symbols": sorted(histories.keys()),
            "errors": history_errors,
            "history_points": history_stats["history_points"],
            "cache": history_payload.get("cache"),
            "cache_key": history_payload.get("cache_key"),
            "cached_at": history_payload.get("cached_at"),
        },
        "allocation": allocation,
        "holdings": holdings,
        "exposures": exposures,
        "alerts": alerts,
        "optimization": optimization,
        "news": news,
        "summary": _build_risk_summary(risk_level, alerts, optimization),
        "profile": profile,
    }


def _trade_history_data(limit: int = 100) -> dict[str, Any]:
    entries = read_recent_trade_log(TRADE_LOG_PATH, limit=limit)
    entries = list(reversed(entries))
    summary = trade_log_summary(TRADE_LOG_PATH)
    dashboard = _dashboard_data()
    unrealized = dashboard.get("metrics", {}).get("total_unrealized_pnl")
    return {
        "log_path": str(TRADE_LOG_PATH),
        "summary": {
            **summary,
            "unrealized_pnl": unrealized,
            "cash": dashboard.get("metrics", {}).get("cash"),
            "positions": len(dashboard.get("holdings", [])),
        },
        "entries": entries,
        "profile": dashboard.get("profile"),
    }


def _investor_profile_data() -> dict[str, Any]:
    dashboard = _dashboard_data()
    return {
        "profile": dashboard.get("profile", {}),
        "metrics": dashboard.get("metrics", {}),
        "alerts": dashboard.get("alerts", []),
    }


def _news_data(lookback: str | None = None) -> dict[str, Any]:
    return _dashboard_news_data(_portfolio_data().get("positions", []), lookback=lookback)


def _submit_trade(payload: dict[str, Any]) -> dict[str, Any]:
    trade = payload.get("trade")
    if not isinstance(trade, dict):
        raise ValueError("trade must be an object.")
    result = apply_trades_to_portfolio([trade])
    return {
        "ok": True,
        "result": {
            "portfolio_path": str(result.portfolio_path),
            "log_path": str(result.log_path),
            "trades_applied": result.trades_applied,
            "buys": result.buys,
            "sells": result.sells,
            "realized_pnl": result.realized_pnl,
            "dividends": result.dividends,
            "deposits": result.deposits,
            "withdrawals": result.withdrawals,
            "cash_after": result.cash_after,
            "positions_after": result.positions_after,
        },
        "trades": _trade_history_data(),
        "portfolio": _portfolio_data(),
        "dashboard": _dashboard_data(),
    }


def _build_dashboard_exposures(rows: list[dict[str, Any]], allocation: list[dict[str, Any]], cash_ratio: float) -> list[dict[str, Any]]:
    text_by_symbol = " ".join(f"{row['symbol']} {row['name']} {row['sector']}" for row in rows).lower()
    sector_text = " ".join(item["name"].lower() for item in allocation)
    tech_weight = sum(float(item["weight"] or 0.0) for item in allocation if any(key in item["name"].lower() for key in ["tech", "科技", "新能源", "半导体", "ai"]))
    china_weight = sum(row["weight"] for row in rows if row["symbol"].endswith((".SH", ".SZ")) or any(key in str(row["name"]) for key in ["中国", "贵州", "招商", "宁德", "比亚迪"]))
    ai_weight = sum(row["weight"] for row in rows if any(key in f"{row['symbol']} {row['name']} {row['sector']}".lower() for key in ["ai", "nvda", "nvidia", "半导体", "算力", "芯片"]))
    finance_weight = sum(float(item["weight"] or 0.0) for item in allocation if any(key in item["name"].lower() for key in ["bank", "银行", "保险", "financial"]))
    consumer_weight = sum(float(item["weight"] or 0.0) for item in allocation if any(key in item["name"].lower() for key in ["consumer", "消费"]))
    rate_weight = finance_weight + max(0.0, 0.2 - cash_ratio)
    return [
        {"name": "科技暴露", "score": round(min(100, tech_weight * 100), 1)},
        {"name": "AI暴露", "score": round(min(100, ai_weight * 100), 1)},
        {"name": "中国暴露", "score": round(min(100, china_weight * 100), 1)},
        {"name": "金融/利率敏感", "score": round(min(100, rate_weight * 100), 1)},
        {"name": "消费暴露", "score": round(min(100, consumer_weight * 100), 1)},
        {"name": "现金防御", "score": round(min(100, cash_ratio * 100), 1)},
    ]


def _build_dashboard_alerts(
    rows: list[dict[str, Any]],
    allocation: list[dict[str, Any]],
    largest_weight: float,
    cash_ratio: float,
    risk_level: str,
) -> list[dict[str, Any]]:
    alerts = []
    largest = max(rows, key=lambda item: item["weight"], default=None)
    if largest and largest_weight >= 0.25:
        alerts.append(
            {
                "severity": "high" if largest_weight >= 0.35 else "medium",
                "title": f"{largest['symbol']} 单一持仓偏高",
                "detail": f"当前权重约 {largest_weight * 100:.1f}%，需要关注个股波动对组合的放大影响。",
            }
        )
    top_sector = max((item for item in allocation if item["name"] != "Cash"), key=lambda item: item["weight"] or 0.0, default=None)
    if top_sector and (top_sector["weight"] or 0.0) >= 0.45:
        alerts.append(
            {
                "severity": "medium",
                "title": f"{top_sector['name']} 板块集中",
                "detail": f"板块权重约 {(top_sector['weight'] or 0) * 100:.1f}%，组合对该主题或行业较敏感。",
            }
        )
    if cash_ratio < 0.05:
        alerts.append(
            {
                "severity": "medium",
                "title": "现金缓冲偏低",
                "detail": f"现金占比约 {cash_ratio * 100:.1f}%，遇到波动时调仓弹性较弱。",
            }
        )
    if not alerts:
        alerts.append({"severity": "low", "title": "未发现重大集中风险", "detail": f"当前组合风险等级为 {risk_level}，建议继续跟踪市场数据状态。"})
    return alerts


def _build_optimization_suggestions(allocation: list[dict[str, Any]], cash_ratio: float, largest_weight: float) -> list[dict[str, Any]]:
    suggestions = []
    top_sector = max((item for item in allocation if item["name"] != "Cash"), key=lambda item: item["weight"] or 0.0, default=None)
    if top_sector and (top_sector["weight"] or 0.0) > 0.55:
        suggestions.append(
            {
                "title": "降低板块集中度",
                "current": f"{top_sector['name']} {(top_sector['weight'] or 0) * 100:.1f}%",
                "target": f"{top_sector['name']} 45%-55%",
                "rationale": "降低单一行业或主题对组合波动的主导权。",
            }
        )
    if largest_weight > 0.30:
        suggestions.append(
            {
                "title": "控制最大单一持仓",
                "current": f"最大持仓 {largest_weight * 100:.1f}%",
                "target": "单一持仓不超过 25%-30%",
                "rationale": "避免个股事件对组合净值造成过大影响。",
            }
        )
    if cash_ratio < 0.10:
        suggestions.append(
            {
                "title": "提升现金缓冲",
                "current": f"现金 {cash_ratio * 100:.1f}%",
                "target": "现金 10%-15%",
                "rationale": "提高应对回撤和主动调仓的灵活性。",
            }
        )
    return suggestions or [{"title": "维持当前结构", "current": "未发现需要立即调整的结构性问题", "target": "继续监控", "rationale": "等待更多历史收益和新闻映射数据。"}]


def _build_risk_summary(risk_level: str, alerts: list[dict[str, Any]], optimization: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "risk_level": risk_level,
        "main_risks": [item["title"] for item in alerts[:3]],
        "main_opportunities": ["可通过提升现金缓冲和降低集中度改善组合韧性"],
        "theme_changes": ["主题趋势需要接入新闻影响引擎后进一步更新"],
        "agent_action": optimization[0]["title"] if optimization else "继续监控",
    }


def _parse_trade_date(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _avg_holding_days(entries: list[dict[str, Any]]) -> float | None:
    buy_dates: dict[str, list[datetime]] = {}
    durations: list[int] = []
    for entry in sorted(entries, key=lambda item: str(item.get("trade", {}).get("traded_at") or item.get("recorded_at") or "")):
        trade = entry.get("trade", {})
        symbol = str(trade.get("symbol") or "CASH").upper()
        traded_at = _parse_trade_date(trade.get("traded_at") or entry.get("recorded_at"))
        if not traded_at or symbol == "CASH":
            continue
        if trade.get("side") == "buy":
            buy_dates.setdefault(symbol, []).append(traded_at)
        elif trade.get("side") == "sell" and buy_dates.get(symbol):
            first_buy = buy_dates[symbol].pop(0)
            durations.append(max(0, (traded_at - first_buy).days))
    if not durations:
        return None
    return round(sum(durations) / len(durations), 1)


def _score(value: float | None) -> float | None:
    return round(value, 1) if value is not None and math.isfinite(value) else None


def _confidence_label(trade_count: int) -> str:
    if trade_count >= 20:
        return "High"
    if trade_count >= 6:
        return "Medium"
    if trade_count > 0:
        return "Low"
    return "Cold Start"


def _build_profile(
    risk_level: str,
    risk_score: float,
    largest_weight: float,
    cash_ratio: float,
    sector_hhi: float,
    total_assets: float,
    trade_summary: dict[str, Any],
    trade_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    trade_count = int(trade_summary.get("trade_count") or 0)
    turnover = float(trade_summary.get("turnover") or 0.0)
    turnover_rate = turnover / total_assets if total_assets else None
    avg_holding_period = _avg_holding_days(trade_entries)
    win_rate = trade_summary.get("win_rate")
    sells = int(trade_summary.get("sells") or 0)
    losses = int(trade_summary.get("losses") or 0)

    risk_preference_score = min(100.0, risk_score + max(0.0, (turnover_rate or 0.0) - 0.35) * 18)
    if risk_preference_score >= 68:
        risk_profile = "Aggressive"
    elif risk_preference_score >= 38:
        risk_profile = "Balanced"
    else:
        risk_profile = "Conservative"

    note_text = " ".join(str(entry.get("trade", {}).get("note") or "") for entry in trade_entries).lower()
    trend_keywords = ["ai", "算力", "突破", "趋势", "earnings", "news", "momentum"]
    value_keywords = ["估值", "低估", "分红", "现金流", "value", "long"]
    if turnover_rate is not None and turnover_rate > 1.2 and (avg_holding_period is None or avg_holding_period < 45):
        behavior_profile = "Momentum Trader"
    elif any(key in note_text for key in trend_keywords):
        behavior_profile = "Trend Chaser"
    elif any(key in note_text for key in value_keywords):
        behavior_profile = "Value Investor"
    elif avg_holding_period is not None and avg_holding_period >= 180:
        behavior_profile = "Long-term Holder"
    elif largest_weight > 0.28 or sector_hhi > 0.32:
        behavior_profile = "Concentrated Allocator"
    else:
        behavior_profile = "Balanced Allocator"

    take_profit_score = float(win_rate) * 100 if win_rate is not None else None
    stop_loss_score = max(0.0, 100.0 - losses * 18.0) if sells else None
    position_control_score = max(0.0, 100.0 - largest_weight * 160.0 - sector_hhi * 42.0)
    sector_concentration_score = min(100.0, sector_hhi * 100.0)
    cash_discipline_score = max(0.0, 100.0 - abs(cash_ratio - 0.12) * 220.0)

    dimensions = [
        {
            "name": "换手率",
            "score": _score(min(100.0, (turnover_rate or 0.0) * 100)),
            "detail": "越高代表交易越主动",
        },
        {
            "name": "止盈能力",
            "score": _score(take_profit_score),
            "detail": "基于卖出交易胜率",
        },
        {
            "name": "止损纪律",
            "score": _score(stop_loss_score),
            "detail": "基于亏损卖出次数",
        },
        {
            "name": "仓位控制",
            "score": _score(position_control_score),
            "detail": "基于单一持仓和板块集中度",
        },
        {
            "name": "行业集中度",
            "score": _score(sector_concentration_score),
            "detail": "越高代表行业越集中",
        },
        {
            "name": "风险偏好",
            "score": _score(risk_preference_score),
            "detail": "组合风险与交易活跃度综合判断",
        },
    ]

    observations = []
    if trade_count == 0:
        observations.append("尚未记录交易，画像主要来自当前持仓结构。")
    if turnover_rate is not None and turnover_rate > 0.8:
        observations.append("交易换手偏高，适合重点跟踪交易理由和执行纪律。")
    if largest_weight > 0.25:
        observations.append("单一持仓权重较高，行为画像显示存在集中配置倾向。")
    if cash_ratio < 0.08:
        observations.append("现金缓冲偏低，回撤期间的主动调整空间有限。")
    if not observations:
        observations.append("当前画像没有发现明显行为偏差，继续积累交易日志会提高判断置信度。")

    return {
        "risk_profile": risk_profile,
        "behavior_profile": behavior_profile,
        "confidence": _confidence_label(trade_count),
        "sample_size": trade_count,
        "turnover_rate": _pct(turnover_rate),
        "avg_holding_period": avg_holding_period,
        "take_profit_score": _score(take_profit_score),
        "stop_loss_score": _score(stop_loss_score),
        "position_control_score": _score(position_control_score),
        "sector_concentration_score": _score(sector_concentration_score),
        "risk_preference_score": _score(risk_preference_score),
        "cash_discipline_score": _score(cash_discipline_score),
        "dimensions": dimensions,
        "observations": observations,
        "note": "画像来自本地交易日志和当前持仓结构，不上传云端。",
    }


def _build_behavior_alerts(profile: dict[str, Any]) -> list[dict[str, Any]]:
    alerts = []
    if profile.get("confidence") == "Cold Start":
        alerts.append(
            {
                "severity": "low",
                "title": "交易日志尚未形成画像样本",
                "detail": "记录买入理由、卖出原因和现金变动后，Agent 会开始识别行为偏差。",
            }
        )
    if (profile.get("risk_preference_score") or 0) >= 72:
        alerts.append(
            {
                "severity": "medium",
                "title": "风险偏好分数偏高",
                "detail": "当前风险画像更接近 Aggressive，建议检查集中度、现金缓冲和回撤承受能力是否匹配。",
            }
        )
    if (profile.get("position_control_score") or 100) <= 48:
        alerts.append(
            {
                "severity": "medium",
                "title": "仓位控制分数偏低",
                "detail": "最大持仓或行业集中度正在主导组合表现，建议优先做结构性复盘。",
            }
        )
    return alerts


def _run_agent_command(args: list[str]) -> dict[str, Any]:
    command = [sys.executable, "agent.py", *args]
    try:
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "command": " ".join(command),
            "stdout": exc.stdout or "",
            "stderr": f"Command timed out after {COMMAND_TIMEOUT_SECONDS} seconds.",
            "returncode": None,
        }
    return {
        "ok": result.returncode == 0,
        "command": " ".join(command),
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }


class PortClawAppHandler(BaseHTTPRequestHandler):
    server_version = "PortClawApp/0.1"

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        if path == "/":
            self._send_html(APP_HTML)
            return
        if path == "/api/overview":
            self._send_json(_overview_payload())
            return
        if path == "/api/config-options":
            self._send_json(_config_options())
            return
        if path == "/api/dashboard":
            self._send_json(_dashboard_data())
            return
        if path == "/api/investor-profile":
            self._send_json(_investor_profile_data())
            return
        if path == "/api/news":
            query = parse_qs(parsed_url.query)
            self._send_json(_news_data(lookback=(query.get("lookback") or [None])[0]))
            return
        if path == "/api/portfolio":
            self._send_json(_portfolio_data())
            return
        if path == "/api/trades":
            self._send_json(_trade_history_data())
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        payload = self._read_json()
        try:
            if path == "/api/run":
                self._handle_run(payload)
                return
            if path == "/api/ask":
                self._handle_ask(payload)
                return
            if path == "/api/portfolio":
                self._handle_save_portfolio(payload)
                return
            if path == "/api/config":
                self._send_json(_save_runtime_config(payload))
                return
            if path == "/api/cache/clear":
                self._send_json(_clear_runtime_cache())
                return
            if path == "/api/trades":
                self._send_json(_submit_trade(payload))
                return
        except ValueError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("[PortClaw App] " + format % args + "\n")

    def _handle_run(self, payload: dict[str, Any]) -> None:
        action = str(payload.get("action", "")).strip()
        allowed = {
            "status": ["status"],
            "daily": ["daily"],
            "portfolio": ["portfolio"],
            "data-sources": ["data-sources"],
            "models": ["models"],
            "config-show": ["config-show"],
        }
        if action not in allowed:
            raise ValueError("Unsupported action.")
        self._send_json(_run_agent_command(allowed[action]))

    def _handle_ask(self, payload: dict[str, Any]) -> None:
        question = str(payload.get("question", "")).strip()
        if not question:
            raise ValueError("Question is required.")
        self._send_json(_run_agent_command(["ask", question]))

    def _handle_save_portfolio(self, payload: dict[str, Any]) -> None:
        positions = payload.get("positions")
        if not isinstance(positions, list):
            raise ValueError("positions must be a list.")
        normalized = [normalize_position(item) for item in positions if isinstance(item, dict)]
        if not normalized:
            raise ValueError("At least one valid position is required.")
        data = build_portfolio(
            positions=normalized,
            cash=float(payload.get("cash") or 0.0),
            user_id=str(payload.get("user_id") or "local_user"),
            base_currency=str(payload.get("base_currency") or "USD").upper(),
        )
        path = save_portfolio(data, LOCAL_PORTFOLIO_PATH)
        self._send_json({"ok": True, "path": str(path), "portfolio": _portfolio_data()})

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        if not raw:
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object.")
        return data

    def _send_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send_bytes(body, "application/json; charset=utf-8", status)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self._send_bytes(body, "text/html; charset=utf-8", HTTPStatus.OK)

    def _send_bytes(self, body: bytes, content_type: str, status: HTTPStatus) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        try:
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return


APP_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>PortClaw App</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #050505;
      --bg-soft: #0b0b0b;
      --panel: rgba(18, 18, 18, .58);
      --panel-2: rgba(24, 24, 24, .62);
      --panel-3: rgba(30, 30, 30, .50);
      --line: rgba(212, 162, 76, .14);
      --line-strong: rgba(212, 162, 76, .38);
      --text: #f4efe6;
      --muted: #9f978b;
      --accent: #d4a24c;
      --accent-2: #1a7f64;
      --accent-3: #2aae84;
      --warn: #d4a24c;
      --danger: #7f1f1f;
      --success: #2aae84;
      --secondary: #8b6a2b;
      --radius: 10px;
      --terminal: #0b0b0b;
      --terminal-2: #121212;
      --gold-soft: rgba(212, 162, 76, .18);
      --emerald-soft: rgba(42, 174, 132, .16);
      --shadow-deep: rgba(0, 0, 0, .56);
      --terminal-font: "SF Mono", "IBM Plex Mono", "JetBrains Mono", ui-monospace, Menlo, Consolas, monospace;
    }
    * { box-sizing: border-box; }
    ::selection { background: rgba(212,162,76,.30); color: var(--text); }
    *::-webkit-scrollbar { width: 10px; height: 10px; }
    *::-webkit-scrollbar-track { background: rgba(255,255,255,.025); }
    *::-webkit-scrollbar-thumb { background: rgba(212,162,76,.28); border: 2px solid rgba(5,5,5,.86); border-radius: 999px; }
    *::-webkit-scrollbar-thumb:hover { background: rgba(212,162,76,.44); }
    body {
      margin: 0;
      background:
        linear-gradient(90deg, rgba(212,162,76,.025) 0 1px, transparent 1px 72px),
        linear-gradient(180deg, rgba(212,162,76,.020) 0 1px, transparent 1px 72px),
        radial-gradient(circle at 24% -12%, rgba(212, 162, 76, .20), transparent 34%),
        radial-gradient(circle at 90% 10%, rgba(42, 174, 132, .15), transparent 30%),
        radial-gradient(circle at 60% 106%, rgba(139, 106, 43, .16), transparent 36%),
        linear-gradient(135deg, #050505 0%, #0b0b0b 48%, #121212 100%),
        var(--bg);
      color: var(--text);
      font-family: Inter, "SF Pro Display", "Avenir Next", ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "PingFang SC", "Segoe UI", sans-serif;
      letter-spacing: .005em;
      overflow-x: hidden;
    }
    body::before, body::after {
      content: "";
      position: fixed;
      z-index: 0;
      pointer-events: none;
      filter: blur(54px);
      opacity: .28;
      transform: translate3d(0,0,0);
      animation: liquidDrift 22s ease-in-out infinite alternate;
    }
    body::before {
      width: 680px;
      height: 340px;
      left: 21%;
      top: -180px;
      border-radius: 999px;
      background:
        radial-gradient(circle at 34% 30%, rgba(212, 162, 76, .24), transparent 35%),
        radial-gradient(circle at 70% 72%, rgba(42, 174, 132, .10), transparent 48%),
        rgba(18, 18, 18, .62);
    }
    body::after {
      width: 720px;
      height: 360px;
      right: -210px;
      bottom: -220px;
      border-radius: 999px;
      background:
        radial-gradient(circle at 36% 32%, rgba(26, 127, 100, .16), transparent 38%),
        radial-gradient(circle at 70% 70%, rgba(127,31,31,.13), transparent 48%),
        rgba(11, 11, 11, .72);
      animation-duration: 20s;
    }
    @keyframes liquidDrift {
      0% { transform: translate3d(0, 0, 0) scale(1) rotate(0deg); }
      45% { transform: translate3d(42px, 26px, 0) scale(1.05) rotate(10deg); }
      100% { transform: translate3d(-30px, 46px, 0) scale(.98) rotate(-8deg); }
    }
    .ambient-backdrop, .ambient-canvas, .ambient-vignette {
      position: fixed;
      inset: 0;
      pointer-events: none;
    }
    .ambient-backdrop { z-index: 0; overflow: hidden; }
    .ambient-canvas {
      z-index: 0;
      width: 100%;
      height: 100%;
      opacity: .62;
      mix-blend-mode: screen;
    }
    .ambient-vignette {
      z-index: 0;
      background:
        radial-gradient(circle at 50% 50%, transparent 0 42%, rgba(0,0,0,.18) 70%, rgba(0,0,0,.72) 100%),
        linear-gradient(180deg, rgba(0,0,0,.08), rgba(0,0,0,.38));
    }
    .ambient-glow {
      position: absolute;
      width: 34vw;
      height: 34vw;
      min-width: 420px;
      min-height: 420px;
      border-radius: 999px;
      filter: blur(180px);
      opacity: .11;
      transform: translate3d(0,0,0);
      animation: ambientFloat 42s ease-in-out infinite alternate;
      will-change: transform, opacity;
    }
    .ambient-glow.gold {
      left: -8vw;
      top: -12vw;
      background: #d4a24c;
      opacity: .13;
    }
    .ambient-glow.emerald {
      right: -10vw;
      top: -9vw;
      background: #2aae84;
      opacity: .10;
      animation-duration: 52s;
    }
    .ambient-glow.risk {
      left: 22vw;
      right: 0;
      bottom: -19vw;
      width: 56vw;
      height: 30vw;
      background: #7f1f1f;
      opacity: .09;
      filter: blur(230px);
      animation-duration: 64s;
    }
    @keyframes ambientFloat {
      0% { transform: translate3d(0, 0, 0) scale(1); opacity: .08; }
      50% { transform: translate3d(3vw, 2vh, 0) scale(1.08); opacity: .14; }
      100% { transform: translate3d(-2vw, 4vh, 0) scale(.96); opacity: .10; }
    }
    @media (prefers-reduced-motion: reduce) {
      body::before, body::after, .ambient-glow { animation: none; }
      .ambient-canvas { opacity: .38; }
    }
    body.setup-required .shell { display: none; }
    button, input, textarea, select { font: inherit; }
    .setup-gate {
      min-height: 100vh;
      padding: 34px;
      display: none;
      place-items: center;
      position: relative;
      z-index: 1;
    }
    body.setup-required .setup-gate { display: grid; }
    .setup-card {
      width: min(1080px, 100%);
      display: grid;
      grid-template-columns: minmax(300px, .82fr) minmax(420px, 1.18fr);
      gap: 22px;
      padding: 24px;
      border: 1px solid var(--line);
      border-radius: 22px;
      background:
        radial-gradient(circle at 12% 0, rgba(212, 162, 76, .20), transparent 34%),
        linear-gradient(135deg, rgba(18, 18, 18, .68), rgba(11, 11, 11, .54));
      box-shadow: 0 34px 120px rgba(0, 0, 0, .56), 0 0 0 1px rgba(212,162,76,.06) inset;
      backdrop-filter: blur(34px) saturate(1.18);
    }
    .setup-hero {
      padding: 22px;
      border-radius: 10px;
      color: var(--text);
      background:
        linear-gradient(90deg, rgba(212,162,76,.04) 0 1px, transparent 1px 48px),
        linear-gradient(180deg, rgba(18,18,18,.78), rgba(5,5,5,.88)),
        #0b0b0b;
      display: grid;
      align-content: space-between;
      min-height: 560px;
    }
    .setup-hero h2 { font-size: 34px; line-height: 1.06; margin-top: 18px; }
    .setup-hero p { color: rgba(239,232,218,.68); line-height: 1.6; margin-top: 14px; }
    .setup-steps { display: grid; gap: 10px; margin-top: 26px; }
    .setup-step {
      display: grid;
      grid-template-columns: 26px 1fr;
      gap: 10px;
      align-items: start;
      padding: 10px;
      border: 1px solid rgba(212, 162, 76, .12);
      border-radius: 14px;
      background: rgba(255, 255, 255, .035);
    }
    .setup-step span:first-child {
      width: 26px;
      height: 26px;
      display: grid;
      place-items: center;
      border-radius: 999px;
      color: #0b0d12;
      background: linear-gradient(135deg, #d4a24c, #8b6a2b);
      font-weight: 800;
      font-size: 12px;
    }
    .setup-step strong { display: block; font-size: 13px; }
    .setup-step small { color: rgba(239,232,218,.58); line-height: 1.45; }
    .setup-form {
      padding: 22px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(18, 18, 18, .58);
      box-shadow: 0 22px 60px rgba(0,0,0,.28), inset 0 1px 0 rgba(255,255,255,.04);
      backdrop-filter: blur(28px);
    }
    .setup-form h3 { font-size: 22px; margin-bottom: 6px; }
    .setup-form .settings-note { margin-bottom: 16px; }
    .setup-status {
      margin-top: 14px;
      border-radius: 14px;
      padding: 12px;
      color: var(--muted);
      background: rgba(18, 18, 18, .62);
      border: 1px solid var(--line);
      line-height: 1.55;
      font-size: 13px;
    }
    .shell {
      min-height: 100vh;
      display: grid;
      grid-template-columns: 282px minmax(0, 1fr);
      position: relative;
      z-index: 1;
    }
    aside {
      border-right: 1px solid var(--line);
      background:
        linear-gradient(90deg, rgba(212,162,76,.045) 0 1px, transparent 1px 56px),
        linear-gradient(180deg, rgba(42,174,132,.026) 0 1px, transparent 1px 44px),
        radial-gradient(circle at 0 8%, rgba(212,162,76,.11), transparent 30%),
        linear-gradient(180deg, rgba(11, 11, 11, .94), rgba(5, 5, 5, .98)),
        #050505;
      padding: 26px 18px;
      position: sticky;
      top: 0;
      height: 100vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    aside::before {
      content: "";
      position: absolute;
      inset: 0 auto 0 0;
      width: 3px;
      background: linear-gradient(180deg, #d4a24c, rgba(42,174,132,.72), transparent);
      box-shadow: 0 0 44px rgba(212, 162, 76, .34);
    }
    aside::after {
      content: "";
      position: absolute;
      width: 220px;
      height: 220px;
      right: -130px;
      top: 88px;
      border-radius: 999px;
      background: radial-gradient(circle, rgba(212, 162, 76, .12), transparent 70%);
      pointer-events: none;
    }
    aside > * { position: relative; z-index: 1; }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      margin-bottom: 22px;
    }
    .mark {
      width: 38px;
      height: 38px;
      border-radius: 8px;
      display: grid;
      place-items: center;
      color: #090b0f;
      font-weight: 900;
      background:
        linear-gradient(135deg, #d4a24c, #8b6a2b),
        #d4a24c;
      box-shadow: 0 14px 34px rgba(0, 0, 0, .34), inset 0 1px 0 rgba(255,255,255,.32);
    }
    h1, h2, h3, p { margin: 0; }
    a { color: #d8be7a; text-decoration: none; }
    a:hover { color: #f0d999; text-decoration: underline; text-underline-offset: 3px; }
    h1 { font-size: 18px; letter-spacing: .2px; }
    .subtitle { color: var(--muted); font-size: 12px; margin-top: 3px; }
    aside h1, aside .side-status-row span:last-child, aside .nav-copy strong { color: var(--text); }
    aside .subtitle, aside .side-status-row span:first-child, aside .nav-copy span { color: rgba(239,232,218,.56); }
    .side-status {
      display: grid;
      gap: 10px;
      padding: 12px;
      margin-bottom: 18px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background:
        linear-gradient(90deg, rgba(212,162,76,.045) 0 1px, transparent 1px 38px),
        rgba(255, 255, 255, .026);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.035);
    }
    .side-status-row { display: flex; justify-content: space-between; gap: 10px; font-size: 12px; }
    .side-status-row span:first-child { color: var(--muted); }
    .side-status-row span:last-child { color: var(--text); text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    aside .side-status-row span:first-child { color: rgba(239,232,218,.52); }
    aside .side-status-row span:last-child { color: var(--text); }
    nav { display: grid; gap: 8px; }
    nav button {
      width: 100%;
      display: grid;
      grid-template-columns: 28px 1fr;
      align-items: center;
      gap: 10px;
      color: rgba(239,232,218,.64);
      padding: 12px 13px;
      border-radius: 9px;
      border: 1px solid transparent;
      background: transparent;
      text-align: left;
      position: relative;
      overflow: hidden;
      isolation: isolate;
      transition: transform .3s cubic-bezier(.2,.8,.2,1), border-color .3s ease, background .3s ease, box-shadow .3s ease, color .3s ease;
    }
    nav button::before {
      content: "";
      position: absolute;
      inset: 1px;
      border-radius: 8px;
      background:
        linear-gradient(115deg, rgba(212,162,76,.24), rgba(255,255,255,.040) 34%, rgba(42,174,132,.08) 70%, transparent),
        radial-gradient(circle at 0 50%, rgba(212,162,76,.18), transparent 52%);
      opacity: 0;
      transition: opacity .3s ease;
      z-index: 0;
    }
    nav button::after {
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(90deg, rgba(212,162,76,.42), rgba(212,162,76,.10) 42%, transparent 74%);
      opacity: 0;
      transform: translateX(-24px);
      transition: opacity .3s ease, transform .3s cubic-bezier(.2,.8,.2,1);
      z-index: 0;
    }
    nav button:hover, nav button.active {
      color: var(--text);
      background: rgba(255, 255, 255, .040);
      border-color: rgba(212, 162, 76, .28);
      transform: translateX(2px);
      box-shadow: 0 0 26px rgba(212,162,76,.075), inset 0 1px 0 rgba(255,255,255,.06);
    }
    nav button:hover::before, nav button.active::before { opacity: 1; }
    nav button:hover::after, nav button.active::after { opacity: 1; transform: translateX(0); }
    nav button > * { position: relative; z-index: 1; }
    aside nav button:hover, aside nav button.active { color: var(--text); }
    nav button.active {
      box-shadow:
        inset 3px 0 0 rgba(212,162,76,.92),
        0 0 34px rgba(212,162,76,.105),
        inset 0 1px 0 rgba(255,255,255,.08);
    }
    .nav-icon {
      width: 28px;
      height: 28px;
      display: grid;
      place-items: center;
      border-radius: 6px;
      background: rgba(212, 162, 76, .11);
      border: 1px solid rgba(212,162,76,.16);
      color: #d4a24c;
      font-family: var(--terminal-font);
      font-size: 12px;
      font-weight: 800;
    }
    .nav-copy strong { display: block; font-size: 13px; }
    .nav-copy span { display: block; font-size: 11px; color: var(--muted); margin-top: 2px; }
    main { padding: 28px 32px 34px; max-width: 1580px; width: 100%; min-width: 0; position: relative; z-index: 1; }
    .topbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 24px;
      padding: 16px 18px;
      border: 1px solid rgba(212,162,76,.13);
      border-radius: 10px;
      background:
        linear-gradient(90deg, rgba(212,162,76,.032) 0 1px, transparent 1px 52px),
        linear-gradient(180deg, rgba(255,255,255,.038), rgba(255,255,255,.012)),
        rgba(5,5,5,.30);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.04), 0 18px 54px rgba(0,0,0,.22);
      backdrop-filter: blur(22px);
      position: relative;
      overflow: hidden;
    }
    .topbar::before {
      content: "PORTCLAW // LOCAL RISK INTELLIGENCE OS";
      position: absolute;
      right: 18px;
      bottom: 7px;
      color: rgba(212,162,76,.32);
      font-family: var(--terminal-font);
      font-size: 10px;
      letter-spacing: .16em;
    }
    .topbar h2 {
      font-family: "SF Pro Display", Inter, "PingFang SC", ui-sans-serif, system-ui, sans-serif;
      font-size: 34px;
      letter-spacing: -.01em;
      font-weight: 820;
    }
    .actions { display: flex; gap: 10px; flex-wrap: wrap; }
    button {
      border: 1px solid var(--line);
      color: var(--text);
      background:
        linear-gradient(180deg, rgba(255,255,255,.065), rgba(255,255,255,.025)),
        rgba(17, 20, 27, .78);
      border-radius: 8px;
      padding: 12px 16px;
      cursor: pointer;
      box-shadow: inset 0 1px 0 rgba(255,255,255,.055), 0 8px 22px rgba(0,0,0,.18);
      transition: border-color .3s ease, transform .3s cubic-bezier(.2,.8,.2,1), background .3s ease, box-shadow .3s ease, opacity .3s ease;
    }
    button:hover { border-color: var(--line-strong); transform: translateY(-1px); box-shadow: inset 0 1px 0 rgba(255,255,255,.08), 0 12px 28px rgba(0,0,0,.24); }
      button.primary {
      border-color: rgba(212, 162, 76, .52);
      background:
        linear-gradient(180deg, rgba(212, 162, 76, .96), rgba(139, 106, 43, .94)),
        #d4a24c;
      color: #050505;
      box-shadow: 0 18px 46px rgba(0, 0, 0, .36), 0 0 0 1px rgba(255,255,255,.08) inset, 0 0 32px rgba(212,162,76,.12);
    }
    button:disabled { cursor: progress; opacity: .62; }
    .grid { display: grid; gap: 20px; }
    .metrics { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .investment-metrics { grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
    .risk-command { grid-template-columns: minmax(280px, .95fr) minmax(300px, 1.1fr) minmax(280px, .82fr); align-items: stretch; margin-bottom: 20px; }
    .dashboard-grid { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 390px; align-items: start; margin-top: 20px; }
    .dashboard-wide { grid-template-columns: minmax(0, 1.2fr) minmax(0, .8fr); align-items: start; margin-top: 20px; }
    .workspace { grid-template-columns: minmax(0, 1.45fr) minmax(360px, .8fr); align-items: start; }
    .view { display: none; }
    .view.active {
      display: block;
      animation: viewEnter .3s cubic-bezier(.2,.8,.2,1) both;
    }
    @keyframes viewEnter {
      from { opacity: 0; transform: translateY(8px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .hero-grid { grid-template-columns: minmax(0, 1.2fr) minmax(320px, .8fr); align-items: stretch; margin-top: 14px; }
    .feature-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); margin-top: 14px; }
    .card {
      background:
        linear-gradient(90deg, rgba(212,162,76,.022) 0 1px, transparent 1px 42px),
        radial-gradient(circle at 16% 0, rgba(212,162,76,.07), transparent 28%),
        linear-gradient(180deg, rgba(255, 255, 255, .055), rgba(255, 255, 255, .016)),
        var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 22px;
      box-shadow:
        0 28px 90px var(--shadow-deep),
        0 0 0 1px rgba(212,162,76,.045) inset,
        inset 0 1px 0 rgba(255,255,255,.06);
      backdrop-filter: blur(32px) saturate(1.18);
      -webkit-backdrop-filter: blur(32px) saturate(1.18);
      position: relative;
      overflow: hidden;
      transition: transform .3s cubic-bezier(.2,.8,.2,1), box-shadow .3s ease, border-color .3s ease, background .3s ease;
    }
    .card::before {
      content: "";
      position: absolute;
      inset: 0;
      border-radius: inherit;
      background:
        linear-gradient(135deg, rgba(255,255,255,.075), transparent 42%),
        linear-gradient(180deg, rgba(212,162,76,.26), transparent 2px, transparent 100%);
      pointer-events: none;
    }
    .card:hover {
      transform: translateY(-1px);
      border-color: rgba(212, 162, 76, .34);
      box-shadow:
        0 30px 96px rgba(0,0,0,.62),
        0 0 30px rgba(212,162,76,.055),
        0 0 0 1px rgba(212,162,76,.08) inset,
        inset 0 1px 0 rgba(255,255,255,.08);
    }
    .card > * { position: relative; z-index: 1; }
    .metric.card {
      min-height: 116px;
      border-radius: 9px;
      background:
        linear-gradient(180deg, rgba(255,255,255,.050), rgba(255,255,255,.012)),
        rgba(10,10,10,.50);
    }
    .metric.risk-key {
      background:
        radial-gradient(circle at 90% 0, rgba(127, 31, 31, .16), transparent 32%),
        linear-gradient(180deg, rgba(18,18,18,.66), rgba(11,11,11,.52));
      border-color: rgba(127, 31, 31, .26);
    }
    .feature-card {
      min-height: 150px;
      display: grid;
      gap: 12px;
      align-content: space-between;
      text-align: left;
      position: relative;
      overflow: hidden;
    }
    .feature-card::before {
      content: "";
      position: absolute;
      left: 16px;
      right: 16px;
      top: 0;
      height: 2px;
      background: linear-gradient(90deg, var(--accent), transparent);
      opacity: .65;
    }
    .feature-card p { color: var(--muted); font-size: 13px; line-height: 1.45; }
    .hero-card {
      min-height: 290px;
      background:
        linear-gradient(135deg, rgba(212, 162, 76, .14), transparent 36%),
        linear-gradient(180deg, #121212, #0b0b0b);
      overflow: hidden;
      position: relative;
    }
    .hero-card::after {
      content: "";
      position: absolute;
      inset: auto 16px 16px auto;
      width: 210px;
      height: 94px;
      border: 1px solid rgba(212, 162, 76, .18);
      border-radius: 8px;
      background:
        linear-gradient(90deg, transparent 0 18px, rgba(212,162,76,.06) 18px 19px, transparent 19px 38px),
        linear-gradient(180deg, rgba(212,162,76,.13), rgba(42,174,132,.055));
      opacity: .72;
    }
    .hero-card h3 { font-size: 32px; line-height: 1.08; margin-bottom: 12px; max-width: 780px; }
    .hero-card p { color: var(--muted); line-height: 1.55; max-width: 720px; }
    .hero-meta {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 18px;
    }
    .metric .label, .section-label {
      color: var(--muted);
      font-family: var(--terminal-font);
      font-size: 11px;
      margin-bottom: 9px;
      letter-spacing: .12em;
      text-transform: uppercase;
    }
    .metric .value {
      min-width: 0;
      max-width: 100%;
      font-size: clamp(22px, 1.7vw, 28px);
      font-weight: 830;
      letter-spacing: 0;
      line-height: 1.08;
      font-variant-numeric: tabular-nums;
      overflow-wrap: anywhere;
      word-break: normal;
    }
    .metric .value .amount-number,
    .metric .value .amount-currency {
      display: block;
      max-width: 100%;
      overflow-wrap: anywhere;
    }
    .metric .value .amount-currency { margin-top: 4px; }
    .metric .value.positive { color: var(--danger); }
    .metric .value.negative { color: var(--success); }
    .metric .hint { color: var(--muted); font-size: 12px; margin-top: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .inline-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); margin-top: 10px; }
    .inline-metric {
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      background: rgba(18, 18, 18, .48);
      backdrop-filter: blur(20px);
    }
    .panel-title {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin-bottom: 12px;
      padding-bottom: 10px;
      border-bottom: 1px solid rgba(212,162,76,.10);
    }
    .panel-title h3 { font-size: 16px; letter-spacing: -.01em; font-weight: 780; }
    .risk-hero {
      min-height: 318px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(220px, 285px);
      grid-template-rows: 1fr auto;
      gap: 18px 22px;
      align-content: stretch;
      align-items: center;
      color: var(--text);
      border-color: rgba(212, 162, 76, .22);
      background:
        linear-gradient(90deg, rgba(212,162,76,.055) 0 1px, transparent 1px 42px),
        linear-gradient(180deg, rgba(42,174,132,.026) 0 1px, transparent 1px 42px),
        radial-gradient(circle at 78% 20%, rgba(212, 162, 76, .15), transparent 32%),
        radial-gradient(circle at 16% 86%, rgba(42, 174, 132, .12), transparent 36%),
        linear-gradient(145deg, rgba(10, 10, 10, .82), rgba(5, 5, 5, .84));
      box-shadow: 0 34px 116px rgba(0, 0, 0, .60), 0 0 48px rgba(212,162,76,.07), inset 0 1px 0 rgba(255,255,255,.06);
      backdrop-filter: blur(36px) saturate(1.18);
    }
    .risk-hero::after {
      content: "";
      position: absolute;
      width: 320px;
      height: 320px;
      right: -92px;
      bottom: -110px;
      border-radius: 24px;
      border: 1px solid rgba(212, 162, 76, .24);
      background:
        linear-gradient(90deg, rgba(212,162,76,.045) 0 1px, transparent 1px 18px),
        linear-gradient(180deg, rgba(212,162,76,.030) 0 1px, transparent 1px 18px),
        radial-gradient(circle, transparent 43%, rgba(212,162,76,.07) 44%, transparent 65%);
      opacity: .52;
      animation: riskGlow 6.5s ease-in-out infinite;
    }
    @keyframes riskGlow {
      0%, 100% { opacity: .52; transform: translate3d(0,0,0) scale(1); }
      50% { opacity: .78; transform: translate3d(-8px,-5px,0) scale(1.03); }
    }
    .risk-eyebrow {
      color: rgba(212,162,76,.78);
      font-family: var(--terminal-font);
      font-size: 11px;
      letter-spacing: .22em;
      text-transform: uppercase;
      margin-bottom: 10px;
    }
    .risk-hero h3 {
      font-family: "SF Pro Display", Inter, "PingFang SC", ui-sans-serif, system-ui, sans-serif;
      font-size: 42px;
      line-height: 1.05;
      letter-spacing: -.015em;
    }
    .risk-command-copy { align-self: center; }
    .risk-hero p {
      max-width: 420px;
      color: rgba(239,232,218,.68);
      line-height: 1.62;
      font-size: 13px;
      margin-top: 14px;
    }
    .risk-score-orb {
      min-height: 238px;
      border-radius: 12px;
      border: 1px solid rgba(212,162,76,.24);
      display: grid;
      place-items: center;
      align-content: center;
      gap: 7px;
      text-align: center;
      background:
        radial-gradient(circle at 50% 30%, rgba(212,162,76,.26), rgba(212,162,76,.04) 42%, transparent 68%),
        radial-gradient(circle at 54% 70%, rgba(42,174,132,.11), transparent 55%),
        linear-gradient(180deg, rgba(255,255,255,.060), rgba(255,255,255,.018));
      box-shadow:
        0 26px 80px rgba(0,0,0,.42),
        0 0 54px rgba(212,162,76,.12),
        inset 0 1px 0 rgba(255,255,255,.08);
      position: relative;
      overflow: hidden;
    }
    .risk-score-orb::before {
      content: "";
      position: absolute;
      inset: 18px;
      border-radius: 10px;
      border: 1px solid rgba(212,162,76,.20);
      background: radial-gradient(circle, transparent 54%, rgba(212,162,76,.09) 55%, transparent 70%);
      animation: statusBreath 4.8s ease-in-out infinite;
    }
    .risk-score-orb > * { position: relative; z-index: 1; }
    .risk-score-orb span,
    .risk-score-orb small {
      color: rgba(239,232,218,.56);
      font-size: 11px;
      letter-spacing: .16em;
      text-transform: uppercase;
    }
    .risk-score-orb strong {
      font-family: "SF Pro Display", Inter, "PingFang SC", ui-sans-serif, system-ui, sans-serif;
      font-size: 74px;
      line-height: .92;
      letter-spacing: -.055em;
      font-weight: 900;
      color: var(--text);
      text-shadow: 0 0 34px rgba(212,162,76,.22);
      font-variant-numeric: tabular-nums;
    }
    .risk-score-orb em {
      font-style: normal;
      font-size: 20px;
      font-weight: 820;
      letter-spacing: .02em;
    }
    .system-status-grid {
      grid-column: 1 / -1;
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }
    .system-status-item {
      min-width: 0;
      display: grid;
      grid-template-columns: 12px 1fr;
      grid-template-rows: auto auto;
      gap: 3px 9px;
      align-items: center;
      border: 1px solid rgba(212,162,76,.15);
      border-radius: 8px;
      padding: 11px 12px;
      background: rgba(255,255,255,.035);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.045);
    }
    .system-status-item strong {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-family: var(--terminal-font);
      font-size: 11px;
      letter-spacing: .06em;
      text-transform: uppercase;
      color: rgba(239,232,218,.86);
    }
    .system-status-item small {
      grid-column: 2;
      color: rgba(239,232,218,.52);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 11px;
    }
    .status-light {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: rgba(140,135,124,.55);
      box-shadow: 0 0 0 4px rgba(140,135,124,.07);
    }
    .system-status-item.ok .status-light,
    .provider.connected .status-dot,
    .status-dot.connected {
      background: #2aae84;
      box-shadow: 0 0 0 4px rgba(42,174,132,.10), 0 0 18px rgba(42,174,132,.36);
      animation: statusBreath 2.8s ease-in-out infinite;
    }
    .system-status-item.warn .status-light {
      background: #d4a24c;
      box-shadow: 0 0 0 4px rgba(212,162,76,.10), 0 0 18px rgba(212,162,76,.30);
      animation: statusBreath 3.2s ease-in-out infinite;
    }
    .system-status-item.muted .status-light,
    .status-dot.muted {
      background: rgba(154,145,128,.42);
      box-shadow: 0 0 0 4px rgba(154,145,128,.045);
    }
    @keyframes statusBreath {
      0%, 100% { opacity: .72; transform: scale(.96); }
      50% { opacity: 1; transform: scale(1.08); }
    }
    .risk-chip-list {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 18px;
    }
    .risk-chip {
      border: 1px solid rgba(212,162,76,.20);
      border-radius: 7px;
      padding: 7px 10px;
      color: rgba(239,232,218,.82);
      background: rgba(255,255,255,.045);
      font-family: var(--terminal-font);
      font-size: 12px;
      box-shadow: inset 0 1px 0 rgba(255,255,255,.05);
    }
    .risk-distribution-card { min-height: 318px; }
    .risk-histogram {
      display: grid;
      grid-template-columns: repeat(6, minmax(38px, 1fr));
      align-items: end;
      gap: 12px;
      min-height: 230px;
      padding-top: 8px;
    }
    .risk-bar {
      min-width: 0;
      display: grid;
      grid-template-rows: 1fr auto auto;
      gap: 8px;
      height: 226px;
      color: var(--muted);
      font-size: 11px;
      text-align: center;
    }
    .risk-bar-column {
      position: relative;
      align-self: end;
      height: 100%;
      border-radius: 999px 999px 6px 6px;
      background:
        linear-gradient(180deg, rgba(255,255,255,.065), rgba(255,255,255,.018)),
        rgba(12, 15, 20, .88);
      overflow: hidden;
      border: 1px solid rgba(212, 162, 76, .14);
      box-shadow: inset 0 0 18px rgba(0,0,0,.38);
    }
    .risk-bar-column::after {
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(90deg, rgba(255,255,255,.12), transparent 28%, transparent 74%, rgba(255,255,255,.055));
      opacity: .42;
      pointer-events: none;
    }
    .risk-bar-fill {
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      min-height: 5%;
      border-radius: inherit;
      background: linear-gradient(180deg, #7f1f1f, #d4a24c 58%, #2aae84);
      box-shadow: 0 -10px 30px rgba(127, 31, 31, .22), inset 0 1px 0 rgba(255,255,255,.20);
      transition: height .45s ease;
    }
    .risk-bar strong {
      color: rgba(239,232,218,.9);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .risk-radial {
      display: grid;
      grid-template-columns: minmax(150px, 180px) minmax(0, 1fr);
      gap: 14px;
      align-items: center;
      min-height: 230px;
    }
    .risk-radial svg {
      filter: drop-shadow(0 18px 30px rgba(0,0,0,.34));
    }
    .risk-radial-center {
      font-family: "SF Pro Display", Inter, "PingFang SC", ui-sans-serif, system-ui, sans-serif;
      font-size: 18px;
      fill: var(--text);
      font-weight: 800;
    }
    .risk-factor-list { display: grid; gap: 8px; }
    .risk-factor {
      display: grid;
      grid-template-columns: 10px 1fr auto;
      gap: 8px;
      align-items: center;
      color: var(--muted);
      font-size: 12px;
    }
    .risk-factor span:first-child {
      width: 10px;
      height: 10px;
      border-radius: 999px;
    }
    .output {
      min-height: 420px;
      max-height: 620px;
      overflow: auto;
      white-space: pre-wrap;
      color: var(--text);
      background:
        linear-gradient(180deg, rgba(255,255,255,.05), rgba(255,255,255,.018)),
        rgba(11, 11, 11, .62);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px;
      line-height: 1.58;
      font-size: 14px;
      box-shadow: inset 0 1px 0 rgba(255,255,255,.055), inset 0 0 40px rgba(0,0,0,.22);
    }
    .chat-output {
      min-height: 430px;
      max-height: 660px;
      overflow: auto;
      display: grid;
      align-content: start;
      gap: 14px;
      padding: 18px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background:
        radial-gradient(circle at 0 0, rgba(212, 162, 76, .08), transparent 24%),
        linear-gradient(180deg, rgba(18, 18, 18, .66), rgba(5, 5, 5, .54));
      box-shadow: inset 0 1px 0 rgba(255,255,255,.06), inset 0 0 56px rgba(0,0,0,.26);
      backdrop-filter: blur(28px);
    }
    .copilot-card {
      min-height: calc(100vh - 150px);
      padding: 0;
      overflow: hidden;
      background:
        linear-gradient(180deg, rgba(255,255,255,.050), rgba(255,255,255,.012)),
        rgba(10, 10, 10, .42);
    }
    .copilot-card::before { opacity: .62; }
    .chat-shell {
      min-height: calc(100vh - 150px);
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
      position: relative;
      z-index: 1;
    }
    .chat-topbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      padding: 18px 20px;
      border-bottom: 1px solid rgba(212,162,76,.11);
      background:
        linear-gradient(180deg, rgba(255,255,255,.060), rgba(255,255,255,.018)),
        rgba(12,12,12,.50);
      backdrop-filter: blur(28px);
    }
    .chat-model-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      max-width: 100%;
      border: 1px solid rgba(212,162,76,.16);
      border-radius: 999px;
      padding: 9px 13px;
      color: var(--text);
      background: rgba(255,255,255,.055);
      box-shadow: 0 12px 34px rgba(0,0,0,.24), inset 0 1px 0 rgba(255,255,255,.055);
    }
    .chat-model-pill strong { font-size: 15px; }
    .chat-model-pill span { color: var(--muted); font-size: 14px; }
    .chat-top-actions { display: flex; gap: 8px; align-items: center; }
    .chat-icon-button {
      width: 38px;
      height: 38px;
      display: inline-grid;
      place-items: center;
      padding: 0;
      border-radius: 999px;
      color: var(--muted);
      font-size: 18px;
      line-height: 1;
      background: rgba(255,255,255,.045);
    }
    .chat-stream {
      min-height: 0;
      max-height: none;
      overflow: auto;
      display: grid;
      align-content: start;
      gap: 22px;
      padding: 42px min(7vw, 84px) 150px;
      border: 0;
      border-radius: 0;
      background:
        radial-gradient(circle at 22% 0, rgba(212,162,76,.050), transparent 32%),
        radial-gradient(circle at 82% 12%, rgba(42,174,132,.040), transparent 30%);
      box-shadow: none;
    }
    .chat-empty {
      align-self: center;
      justify-self: center;
      max-width: 640px;
      text-align: center;
      color: var(--muted);
      line-height: 1.6;
      padding: 80px 0 120px;
    }
    .chat-empty strong {
      display: block;
      color: var(--text);
      font-size: 28px;
      margin-bottom: 10px;
    }
    .chat-composer-wrap {
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      padding: 22px min(7vw, 84px) 24px;
      background: linear-gradient(180deg, transparent, rgba(5,5,5,.82) 28%, rgba(5,5,5,.95));
      pointer-events: none;
    }
    .copilot-card .askbox.chat-composer {
      display: grid;
      grid-template-columns: auto 1fr auto auto;
      align-items: end;
      gap: 10px;
      max-width: 980px;
      margin: 0 auto;
      padding: 10px;
      border: 1px solid rgba(239,232,218,.12);
      border-radius: 26px;
      background:
        linear-gradient(180deg, rgba(255,255,255,.080), rgba(255,255,255,.030)),
        rgba(18,18,18,.88);
      box-shadow: 0 26px 80px rgba(0,0,0,.46), inset 0 1px 0 rgba(255,255,255,.08);
      backdrop-filter: blur(34px);
      pointer-events: auto;
    }
    .chat-plus-button {
      width: 42px;
      height: 42px;
      display: inline-grid;
      place-items: center;
      padding: 0;
      border-radius: 999px;
      font-size: 26px;
      color: var(--muted);
      background: rgba(255,255,255,.055);
    }
    .copilot-card textarea {
      min-height: 46px;
      max-height: 150px;
      resize: vertical;
      border: 0;
      border-radius: 18px;
      background: transparent;
      font-size: 16px;
      line-height: 1.5;
      padding: 11px 4px;
      box-shadow: none;
    }
    .copilot-card textarea:focus {
      border-color: transparent;
      box-shadow: none;
      background: transparent;
    }
    .chat-mode-label {
      align-self: center;
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }
    .copilot-card .askbox button.chat-send-button {
      width: 44px;
      height: 44px;
      min-width: 44px;
      align-self: end;
      display: inline-grid;
      place-items: center;
      padding: 0;
      border-radius: 999px;
      font-size: 22px;
      font-weight: 800;
    }
    .message {
      display: grid;
      gap: 8px;
      max-width: min(760px, 88%);
      animation: messageEnter .3s cubic-bezier(.2,.8,.2,1) both;
    }
    @keyframes messageEnter {
      from { opacity: 0; transform: translateY(6px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .message.user { justify-self: end; }
    .message.agent { justify-self: start; }
    .message.system { justify-self: center; max-width: min(720px, 92%); }
    .message-meta {
      color: var(--muted);
      font-size: 12px;
      padding: 0 4px;
    }
    .message.user .message-meta { text-align: right; }
    .bubble {
      border: 1px solid rgba(239,232,218,.10);
      border-radius: 20px;
      padding: 14px 17px;
      line-height: 1.62;
      white-space: pre-wrap;
      background: rgba(18, 18, 18, .50);
      box-shadow: 0 14px 36px rgba(0, 0, 0, .22);
      backdrop-filter: blur(22px);
    }
    .message.user .bubble {
      border-radius: 24px;
      background: rgba(239,232,218,.12);
      color: var(--text);
      border-color: rgba(239,232,218,.12);
    }
    .message.agent .bubble {
      border-radius: 10px;
      border-color: transparent;
      background: transparent;
      box-shadow: none;
      padding: 4px 0;
      font-size: 15px;
    }
    .message.system .bubble {
      color: var(--muted);
      background: rgba(255, 255, 255, .050);
      box-shadow: none;
    }
    .status-output {
      min-height: 180px;
      max-height: 360px;
      overflow: auto;
      display: grid;
      gap: 10px;
      padding: 12px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(11, 11, 11, .54);
      backdrop-filter: blur(24px);
    }
    .status-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 13px 14px;
      background:
        linear-gradient(90deg, rgba(212,162,76,.026) 0 1px, transparent 1px 38px),
        rgba(18, 18, 18, .56);
      line-height: 1.55;
      color: var(--text);
    }
    .status-card small { display: block; color: var(--muted); margin-top: 4px; }
    .askbox { display: grid; grid-template-columns: 1fr auto; gap: 10px; margin-bottom: 12px; }
    textarea, input {
      width: 100%;
      color: var(--text);
      background: rgba(11, 11, 11, .56);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px 14px;
      outline: none;
      box-shadow: inset 0 1px 0 rgba(255,255,255,.035);
    }
    select {
      width: 100%;
      color: var(--text);
      background: rgba(11, 11, 11, .56);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px 14px;
      outline: none;
      box-shadow: inset 0 1px 0 rgba(255,255,255,.035);
    }
    textarea:focus, input:focus, select:focus { border-color: rgba(212,162,76,.46); box-shadow: 0 0 0 4px rgba(212,162,76,.08), inset 0 1px 0 rgba(255,255,255,.045); }
    textarea { min-height: 88px; resize: vertical; }
    .form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .form-field { display: grid; gap: 7px; }
    .form-field label { color: var(--muted); font-size: 12px; }
    .form-field.full { grid-column: 1 / -1; }
    .secret-row { display: grid; grid-template-columns: 1fr auto; gap: 8px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border-bottom: 1px solid var(--line); padding: 9px 7px; text-align: left; font-size: 13px; }
    th { color: var(--muted); font-weight: 600; }
    tbody tr { transition: background .16s ease; }
    tbody tr:hover { background: rgba(212,162,76,.055); }
    td input { padding: 8px; min-width: 88px; }
    .portfolio-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 12px; }
    .stack { display: grid; gap: 14px; }
    .pill {
      display: inline-flex;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 4px 9px;
      color: var(--muted);
      font-family: var(--terminal-font);
      font-size: 12px;
      background: rgba(255,255,255,.035);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.035);
    }
    .pill.ok { color: var(--success); border-color: rgba(42, 174, 132, .34); }
    .pill.warn { color: var(--warn); border-color: rgba(212, 162, 76, .35); }
    .muted { color: var(--muted); }
    .provider-list { display: grid; gap: 8px; max-height: 270px; overflow: auto; }
    .provider {
      display: grid;
      grid-template-columns: 12px 1fr auto;
      gap: 8px;
      align-items: start;
      border: 1px solid transparent;
      border-color: var(--line);
      padding: 14px;
      border-radius: 9px;
      background:
        linear-gradient(180deg, rgba(255,255,255,.050), rgba(255,255,255,.016)),
        rgba(18,18,18,.42);
      backdrop-filter: blur(18px);
      transition: border-color .3s ease, background .3s ease, box-shadow .3s ease, transform .3s cubic-bezier(.2,.8,.2,1);
    }
    .provider:hover {
      transform: translateY(-1px);
      border-color: rgba(212,162,76,.26);
      box-shadow: 0 16px 42px rgba(0,0,0,.25), 0 0 28px rgba(212,162,76,.055);
    }
    .provider.connected {
      border-color: rgba(42,174,132,.30);
      background:
        radial-gradient(circle at 100% 0, rgba(42,174,132,.10), transparent 38%),
        linear-gradient(180deg, rgba(255,255,255,.055), rgba(255,255,255,.018)),
        rgba(18,18,18,.44);
    }
    .provider.planned {
      opacity: .68;
      border-color: rgba(255,255,255,.07);
    }
    .provider strong { font-size: 13px; }
    .provider small { color: var(--muted); display: block; margin-top: 3px; }
    .provider-status {
      display: grid;
      justify-items: end;
      gap: 6px;
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .05em;
    }
    .status-dot {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      margin-top: 3px;
      background: rgba(154,145,128,.52);
      box-shadow: 0 0 0 4px rgba(154,145,128,.06);
    }
    .toast {
      min-height: 22px;
      color: var(--muted);
      margin-top: 10px;
      font-size: 13px;
    }
    .time-scope {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 20px;
    }
    .time-scope-item {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px 14px;
      background:
        linear-gradient(90deg, rgba(212,162,76,.026) 0 1px, transparent 1px 38px),
        linear-gradient(180deg, rgba(255,255,255,.045), rgba(255,255,255,.014));
      backdrop-filter: blur(18px);
      color: var(--muted);
      min-height: 58px;
    }
    .time-scope-item span { display: block; font-family: var(--terminal-font); font-size: 10px; letter-spacing: .12em; text-transform: uppercase; margin-bottom: 4px; }
    .time-scope-item strong { display: block; color: var(--text); font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .news-tabs { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
    .calendar-panel { margin-top: 14px; }
    .pnl-calendar {
      display: grid;
      grid-template-columns: repeat(7, minmax(0, 1fr));
      gap: 10px;
    }
    .calendar-cell {
      min-height: 74px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: rgba(18,18,18,.50);
      display: grid;
      align-content: space-between;
      gap: 5px;
      color: var(--muted);
      font-size: 11px;
    }
    .calendar-cell.header {
      min-height: auto;
      background: transparent;
      border-color: transparent;
      font-weight: 700;
      color: var(--muted);
      text-align: center;
    }
    .calendar-cell.empty { opacity: .34; }
    .calendar-cell .day-num { color: var(--text); font-weight: 700; font-size: 13px; }
    .calendar-cell .pnl { font-weight: 700; color: var(--muted); }
    .calendar-cell.positive { background: rgba(127, 31, 31, .16); border-color: rgba(127, 31, 31, .30); }
    .calendar-cell.positive .pnl { color: var(--danger); }
    .calendar-cell.negative { background: rgba(42, 174, 132, .12); border-color: rgba(42, 174, 132, .26); }
    .calendar-cell.negative .pnl { color: var(--success); }
    .chart-box { min-height: 280px; display: grid; gap: 12px; }
    .pie-wrap { display: grid; grid-template-columns: 180px 1fr; gap: 14px; align-items: center; }
    .legend { display: grid; gap: 8px; }
    .legend-row { display: grid; grid-template-columns: 10px 1fr auto; gap: 8px; align-items: center; color: var(--muted); font-size: 12px; }
    .legend-dot { width: 10px; height: 10px; border-radius: 999px; }
    .bar-list, .alert-list, .suggestion-list, .exposure-list { display: grid; gap: 12px; }
    .bar-row { display: grid; gap: 6px; }
    .bar-head { display: flex; justify-content: space-between; gap: 10px; color: var(--muted); font-size: 12px; }
    .bar-track { height: 9px; border-radius: 999px; background: rgba(255,255,255,.045); overflow: hidden; border: 1px solid rgba(212,162,76,.11); }
    .bar-fill {
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, rgba(42,174,132,.94), rgba(212,162,76,.96));
      box-shadow: 0 0 22px rgba(212,162,76,.16), inset 0 1px 0 rgba(255,255,255,.24);
      transition: width .42s cubic-bezier(.2,.8,.2,1);
    }
    .alert-item, .suggestion-item {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      background:
        linear-gradient(90deg, rgba(212,162,76,.024) 0 1px, transparent 1px 36px),
        rgba(18,18,18,.50);
      backdrop-filter: blur(18px);
    }
    .alert-item strong, .suggestion-item strong { display: block; margin-bottom: 5px; }
    .alert-item p, .suggestion-item p { color: var(--muted); font-size: 12px; line-height: 1.45; }
    .profile-head {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }
    .profile-tile {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      background:
        linear-gradient(90deg, rgba(212,162,76,.024) 0 1px, transparent 1px 36px),
        linear-gradient(180deg, rgba(255,255,255,.045), rgba(255,255,255,.014));
      backdrop-filter: blur(18px);
    }
    .profile-tile span { display: block; color: var(--muted); font-size: 11px; margin-bottom: 5px; }
    .profile-tile strong { font-size: 18px; letter-spacing: .1px; }
    .profile-list { display: grid; gap: 9px; }
    .profile-row { display: grid; gap: 6px; }
    .profile-row .bar-head { font-size: 11px; }
    .profile-observations {
      display: grid;
      gap: 8px;
      margin-top: 12px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }
    .profile-observations div {
      border-left: 2px solid rgba(212, 162, 76, .45);
      padding-left: 9px;
    }
    .news-panel { margin-top: 20px; }
    .news-list {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }
    .news-item {
      border: 1px solid var(--line);
      border-radius: 9px;
      padding: 16px;
      background:
        linear-gradient(90deg, rgba(212,162,76,.024) 0 1px, transparent 1px 38px),
        rgba(18,18,18,.50);
      backdrop-filter: blur(20px);
      display: grid;
      gap: 8px;
      min-height: 128px;
    }
    .news-item strong {
      font-size: 14px;
      line-height: 1.45;
    }
    .news-item p {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.55;
    }
    .news-meta {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      color: var(--muted);
      font-size: 11px;
    }
    .news-symbols {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }
    .news-empty {
      border: 1px dashed var(--line-strong);
      border-radius: 9px;
      padding: 18px;
      color: var(--muted);
      background: rgba(18,18,18,.46);
      backdrop-filter: blur(18px);
      line-height: 1.6;
    }
    .risk-high { color: var(--danger); border-color: rgba(127, 31, 31, .45); }
    .risk-medium { color: var(--warn); border-color: rgba(212, 162, 76, .40); }
    .risk-low { color: var(--success); border-color: rgba(42, 174, 132, .36); }
    .settings-layout { grid-template-columns: minmax(0, 1.35fr) 360px; align-items: start; }
    .settings-card { padding: 22px; }
    .settings-card .panel-title { margin-bottom: 16px; }
    .settings-note {
      line-height: 1.6;
      color: var(--muted);
      font-size: 13px;
    }
    .provider-note {
      display: grid;
      gap: 8px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(18,18,18,.50);
      backdrop-filter: blur(20px);
    }
    .provider-note-row {
      display: flex;
      justify-content: space-between;
      gap: 14px;
      color: var(--muted);
      font-size: 12px;
    }
    .provider-note-row strong { color: var(--text); font-weight: 650; text-align: right; }
    .config-summary {
      display: grid;
      gap: 10px;
      margin: 16px 0;
    }
    .config-summary-item {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      background:
        linear-gradient(90deg, rgba(212,162,76,.024) 0 1px, transparent 1px 38px),
        rgba(18,18,18,.50);
      backdrop-filter: blur(20px);
    }
    .config-summary-item span { display: block; color: var(--muted); font-size: 12px; margin-bottom: 4px; }
    .config-summary-item strong { display: block; font-size: 15px; }
    @media (max-width: 1320px) {
      .risk-command { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .risk-hero {
        grid-column: 1 / -1;
        min-height: 236px;
      }
      .risk-hero h3 { font-size: 31px; }
      .risk-score-orb strong { font-size: 58px; }
      .system-status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .risk-distribution-card { min-height: 286px; }
      .risk-histogram { min-height: 208px; }
      .risk-bar { height: 204px; }
    }
    @media (max-width: 980px) {
      .shell { grid-template-columns: 1fr; }
      aside { position: relative; height: auto; }
      .metrics, .investment-metrics, .workspace, .settings-layout, .dashboard-grid, .dashboard-wide, .risk-command, .hero-grid, .feature-grid, .news-list, .setup-card { grid-template-columns: 1fr; }
      .setup-gate { padding: 16px; }
      .setup-hero { min-height: auto; }
      .time-scope { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .pie-wrap, .risk-radial { grid-template-columns: 1fr; justify-items: center; }
      .risk-hero { grid-template-columns: 1fr; }
      .system-status-grid { grid-template-columns: 1fr; }
      .risk-histogram { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .portfolio-grid { grid-template-columns: 1fr; }
      .askbox { grid-template-columns: 1fr; }
      .chat-stream { padding: 28px 18px 150px; }
      .chat-composer-wrap { padding: 18px; }
      .copilot-card .askbox.chat-composer { grid-template-columns: auto 1fr auto; border-radius: 22px; }
      .chat-mode-label { display: none; }
      .copilot-card .askbox button.chat-send-button,
      .copilot-card .askbox button.chat-plus-button { width: 42px; }
    }
  </style>
</head>
<body class="setup-required">
  <div class="ambient-backdrop" aria-hidden="true">
    <div class="ambient-glow gold"></div>
    <div class="ambient-glow emerald"></div>
    <div class="ambient-glow risk"></div>
  </div>
  <canvas id="ambientCanvas" class="ambient-canvas" aria-hidden="true"></canvas>
  <div class="ambient-vignette" aria-hidden="true"></div>
  <section id="setupGate" class="setup-gate">
    <div class="setup-card">
      <div class="setup-hero">
        <div>
          <div class="brand">
            <div class="mark">PC</div>
            <div>
              <h1>PortClaw</h1>
              <div class="subtitle">First-run setup</div>
            </div>
          </div>
          <h2>先完成投资终端的基础连接。</h2>
          <p>第一次启动时，PortClaw 会先要求配置模型与市场数据源。完成后才开放组合、日报、问答和交易日志功能；下一次启动会直接进入主界面。</p>
        </div>
        <div class="setup-steps">
          <div class="setup-step"><span>1</span><div><strong>语言与本地偏好</strong><small>先选择界面语言和基础缓存策略。</small></div></div>
          <div class="setup-step"><span>2</span><div><strong>模型配置</strong><small>选择本地模板、DeepSeek、Qwen、OpenAI 或兼容接口。</small></div></div>
          <div class="setup-step"><span>3</span><div><strong>数据源配置</strong><small>选择 Demo、Yahoo、Tushare 等供应商，按需填写 token。</small></div></div>
          <div class="setup-step"><span>4</span><div><strong>进入 Portfolio OS</strong><small>配置保存在本机 local_config.json，不会自动上传。</small></div></div>
        </div>
      </div>
      <div class="setup-form">
        <h3>启动配置</h3>
        <p class="settings-note">如果只是体验 UI，可以选择 Local Template + Demo Local Data；如果要接真实 A 股数据，选择 Tushare 并填写 token。</p>
        <div class="form-grid">
          <div class="form-field">
            <label for="setupLanguage">Language</label>
            <select id="setupLanguage"></select>
          </div>
          <div class="form-field">
            <label for="setupCachePolicy">Cache Policy</label>
            <select id="setupCachePolicy"></select>
          </div>
          <div class="form-field full">
            <label for="setupTimezone">Time Zone</label>
            <select id="setupTimezone"></select>
          </div>
          <div class="form-field">
            <label for="setupLlmProvider">LLM Provider</label>
            <select id="setupLlmProvider" onchange="updateSetupModelOptions()"></select>
          </div>
          <div class="form-field">
            <label for="setupLlmModel">Model</label>
            <select id="setupLlmModel"></select>
          </div>
          <div class="form-field full">
            <label for="setupLlmBaseUrl">LLM Base URL</label>
            <input id="setupLlmBaseUrl" placeholder="默认或自定义 OpenAI-compatible endpoint" />
          </div>
          <div class="form-field full">
            <label for="setupLlmApiKey">LLM API Key</label>
            <input id="setupLlmApiKey" type="password" placeholder="Local Template 可留空；远程模型请填写 key" />
          </div>
          <div class="form-field">
            <label for="setupMarketProvider">Market Provider</label>
            <select id="setupMarketProvider" onchange="renderSetupMarketHint()"></select>
          </div>
          <div class="form-field">
            <label for="setupMarketBaseUrl">Market Base URL</label>
            <input id="setupMarketBaseUrl" placeholder="通常留空" />
          </div>
          <div class="form-field full">
            <label for="setupMarketApiKey">Market API Key / Token</label>
            <input id="setupMarketApiKey" type="password" placeholder="Tushare token / provider API key" />
          </div>
          <div class="form-field">
            <label for="setupNewsProvider">News Source</label>
            <select id="setupNewsProvider"></select>
          </div>
          <div class="form-field">
            <label for="setupNewsLookback">Default News Window</label>
            <select id="setupNewsLookback"></select>
          </div>
          <div class="form-field full">
            <label>Provider Notes</label>
            <div id="setupMarketHint" class="provider-note"></div>
          </div>
        </div>
        <div class="actions" style="margin-top:16px">
          <button class="primary" onclick="completeSetup()">完成配置并进入</button>
        </div>
        <div id="setupStatus" class="setup-status">等待配置。远程模型和需要认证的数据源必须填写对应 key / token。</div>
      </div>
    </div>
  </section>
  <div id="appShell" class="shell">
    <aside>
      <div class="brand">
        <div class="mark">PC</div>
        <div>
          <h1>PortClaw</h1>
          <div class="subtitle">Institutional AI Risk Terminal</div>
        </div>
      </div>
      <div class="side-status">
        <div class="side-status-row"><span>Provider</span><span id="sideProvider">-</span></div>
        <div class="side-status-row"><span>Model</span><span id="sideModel">-</span></div>
        <div class="side-status-row"><span>Positions</span><span id="sidePositions">-</span></div>
      </div>
      <nav>
        <button class="active" data-view="dashboard" onclick="showView('dashboard')"><span class="nav-icon">总</span><span class="nav-copy"><strong>总览</strong><span>资产与运行状态</span></span></button>
        <button data-view="daily" onclick="showView('daily')"><span class="nav-icon">报</span><span class="nav-copy"><strong>风险日报</strong><span>生成今日分析</span></span></button>
        <button data-view="ask" onclick="showView('ask')"><span class="nav-icon">问</span><span class="nav-copy"><strong>组合问答</strong><span>自由追问风险</span></span></button>
        <button data-view="portfolio" onclick="showView('portfolio')"><span class="nav-icon">仓</span><span class="nav-copy"><strong>持仓管理</strong><span>编辑本地组合</span></span></button>
        <button data-view="trades" onclick="showView('trades')"><span class="nav-icon">交</span><span class="nav-copy"><strong>交易日志</strong><span>收益与行为记录</span></span></button>
        <button data-view="sources" onclick="showView('sources')"><span class="nav-icon">源</span><span class="nav-copy"><strong>数据源</strong><span>模型与供应商</span></span></button>
        <button data-view="settings" onclick="showView('settings')"><span class="nav-icon">设</span><span class="nav-copy"><strong>设置</strong><span>语言、模型与数据源</span></span></button>
      </nav>
    </aside>
    <main>
      <section class="topbar">
        <div>
          <h2 id="pageTitle">机构级组合风险终端</h2>
          <p id="pageSubtitle" class="subtitle">Local-first intelligence layer for portfolio risk, exposure, market data and agentic surveillance.</p>
        </div>
        <div class="actions">
          <button onclick="refreshDashboardData()">刷新状态</button>
          <button class="primary" onclick="showView('daily'); runAction('daily')">生成今日风险日报</button>
        </div>
      </section>

      <section id="view-dashboard" class="view active">
        <div class="time-scope">
          <div class="time-scope-item"><span>Time Zone</span><strong id="dashTimezone">-</strong></div>
          <div class="time-scope-item"><span>Latest Close</span><strong id="dashTodayBoundary">-</strong></div>
          <div class="time-scope-item"><span>Week Start</span><strong id="dashWeekBoundary">-</strong></div>
          <div class="time-scope-item"><span>Month / YTD</span><strong id="dashMonthBoundary">-</strong></div>
        </div>
        <div class="grid risk-command">
          <div class="card risk-hero">
            <div class="risk-command-copy">
              <div class="risk-eyebrow">Risk Command Center</div>
              <h3>组合风险指挥中心</h3>
              <p id="riskHeroNarrative">正在读取持仓、行情与交易日志，构建今天的风险视图。</p>
              <div id="riskPulseList" class="risk-chip-list"></div>
            </div>
            <div class="risk-score-orb">
              <span>Risk Score</span>
              <strong id="riskHeroScoreValue">-</strong>
              <em id="riskHeroLevel">-</em>
              <small id="riskHeroScore">score -</small>
            </div>
            <div class="system-status-grid">
              <div class="system-status-item muted" id="statusPortfolioEngine"><span class="status-light"></span><strong>Portfolio Engine Active</strong><small>-</small></div>
              <div class="system-status-item muted" id="statusMarketData"><span class="status-light"></span><strong>Market Data Connected</strong><small>-</small></div>
              <div class="system-status-item muted" id="statusNewsEngine"><span class="status-light"></span><strong>News Engine Running</strong><small>-</small></div>
              <div class="system-status-item muted" id="statusRiskUpdated"><span class="status-light"></span><strong>Risk Analysis Updated</strong><small>-</small></div>
            </div>
          </div>
          <div class="card risk-distribution-card">
            <div class="panel-title"><h3>风险分布直方图</h3><span class="pill">Risk Histogram</span></div>
            <div id="riskHistogram" class="risk-histogram"></div>
          </div>
          <div class="card risk-distribution-card">
            <div class="panel-title"><h3>风险因子扇形图</h3><span class="pill">Factor Pie</span></div>
            <div id="riskRadial" class="risk-radial"></div>
          </div>
        </div>
        <div class="grid investment-metrics">
          <div class="card metric"><div class="label">总资产</div><div id="dashTotalAssets" class="value">-</div><div id="dashCash" class="hint">cash -</div></div>
          <div class="card metric"><div class="label">昨日收益</div><div id="dashTodayPnl" class="value">-</div><div id="dashTodayReturn" class="hint">history status</div></div>
          <div class="card metric"><div class="label">本周收益</div><div id="dashWeekReturn" class="value">-</div><div id="dashWeekHint" class="hint">需要历史行情</div></div>
          <div class="card metric"><div class="label">本月收益</div><div id="dashMonthReturn" class="value">-</div><div id="dashMonthHint" class="hint">需要历史行情</div></div>
          <div class="card metric"><div class="label">YTD 收益</div><div id="dashYtdReturn" class="value">-</div><div id="dashUnrealized" class="hint">unrealized -</div></div>
          <div class="card metric risk-key"><div class="label">风险等级</div><div id="dashRiskLevel" class="value">-</div><div id="dashRiskScore" class="hint">score -</div></div>
          <div class="card metric risk-key"><div class="label">本周最大回撤</div><div id="dashMaxDrawdown" class="value">-</div><div id="dashDrawdownHint" class="hint">需要历史净值</div></div>
          <div class="card metric risk-key"><div class="label">波动率</div><div id="dashVolatility" class="value">-</div><div id="dashVolHint" class="hint">需要历史净值</div></div>
          <div class="card metric risk-key"><div class="label">Sharpe Ratio</div><div id="dashSharpe" class="value">-</div><div id="dashSharpeHint" class="hint">需要历史净值</div></div>
          <div class="card metric"><div class="label">现金占比</div><div id="dashCashRatio" class="value">-</div><div id="dashLargestWeight" class="hint">largest -</div></div>
        </div>

        <div class="card calendar-panel">
          <div class="panel-title"><h3>月度收益日历</h3><span id="calendarMonth" class="pill">calendar</span></div>
          <div id="pnlCalendar" class="pnl-calendar"></div>
        </div>

        <div class="grid dashboard-grid">
          <div class="card chart-box">
            <div class="panel-title"><h3>资产配置</h3><span class="pill">Allocation</span></div>
            <div id="allocationChart" class="pie-wrap"></div>
          </div>
          <div class="card chart-box">
            <div class="panel-title"><h3>持仓权重</h3><span class="pill">Weights</span></div>
            <div id="holdingWeightChart" class="bar-list"></div>
          </div>
          <div class="card">
            <div class="panel-title"><h3>Today's Risk Summary</h3><span id="runState" class="pill">ready</span></div>
            <div id="riskSummaryPanel"></div>
          </div>
        </div>

        <div class="grid dashboard-wide">
          <div class="card chart-box">
            <div class="panel-title"><h3>风险暴露分析</h3><span class="pill">Exposure Matrix</span></div>
            <div id="exposureChart" class="exposure-list"></div>
          </div>
          <div class="card">
            <div class="panel-title"><h3>Agent 主动发现</h3><span id="dashProfile" class="pill">profile</span></div>
            <div id="agentAlerts" class="alert-list"></div>
            <div class="panel-title" style="margin-top:16px"><h3>用户画像</h3><span id="profileConfidence" class="pill">confidence</span></div>
            <div id="investorProfilePanel"></div>
            <div class="panel-title" style="margin-top:16px"><h3>组合优化建议</h3><span class="pill">No stock picks</span></div>
            <div id="optimizationList" class="suggestion-list"></div>
          </div>
        </div>
        <div class="card news-panel">
          <div class="panel-title">
            <h3>组合相关新闻</h3>
            <div class="actions"><span id="newsStatus" class="pill">news</span><button onclick="refreshNews()">刷新新闻</button></div>
          </div>
          <div class="news-tabs">
            <button data-news-lookback="today" onclick="setNewsLookback('today')">今日新闻</button>
            <button data-news-lookback="7d" onclick="setNewsLookback('7d')">七日内新闻</button>
            <button data-news-lookback="1m" onclick="setNewsLookback('1m')">一个月内新闻</button>
            <button data-news-lookback="6m" onclick="setNewsLookback('6m')">半年内新闻</button>
          </div>
          <div id="portfolioNewsList" class="news-list"></div>
        </div>
      </section>

      <section id="view-daily" class="view">
        <div class="grid workspace">
          <div class="card">
            <div class="panel-title"><h3>风险日报</h3><span class="pill">Agent briefing</span></div>
            <div class="actions" style="margin-bottom:12px">
              <button class="primary" onclick="runAction('daily')">生成今日风险日报</button>
              <button onclick="runAction('portfolio')">解释当前持仓</button>
              <button onclick="runAction('status')">刷新运行状态</button>
            </div>
            <div class="chat-output" id="dailyOutput">
              <div class="message system"><div class="bubble">点击“生成今日风险日报”，PortClaw 会以 briefing 形式总结组合风险、数据状态与优先行动。</div></div>
            </div>
          </div>
          <div class="card">
            <div class="panel-title"><h3>日报工作流</h3><span class="pill ok">structured</span></div>
            <p class="muted" style="line-height:1.6">这一步会加载本地持仓，拉取可用市场数据，计算指标和风险主题，再生成报告。输出里会保留数据源状态和 fallback 原因，方便判断哪些结论来自实时数据。</p>
          </div>
        </div>
      </section>

      <section id="view-ask" class="view">
        <div class="card copilot-card">
          <div class="chat-shell">
            <div class="chat-topbar">
              <div class="chat-model-pill"><strong>PortClaw</strong><span>Intelligence</span></div>
              <div class="chat-top-actions">
                <button class="chat-icon-button" title="刷新状态" onclick="askPreset('当前数据源和组合状态是否正常？')">↻</button>
                <button class="chat-icon-button" title="解释持仓" onclick="askPreset('解释当前持仓结构和最重要的风险。')">⌁</button>
              </div>
            </div>
            <div id="askOutput" class="chat-output chat-stream">
              <div class="chat-empty"><strong>有问题，尽管问</strong>基于当前持仓、交易记录、市场数据状态和风险画像回答。</div>
            </div>
            <div class="chat-composer-wrap">
              <div class="askbox chat-composer">
                <button class="chat-plus-button" title="新问题" onclick="document.getElementById('question').focus()">+</button>
                <textarea id="question" rows="1" placeholder="Ask anything" onkeydown="handleQuestionKey(event)"></textarea>
                <span class="chat-mode-label">Risk Desk</span>
                <button class="primary chat-send-button" title="发送" onclick="askQuestion()">↑</button>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="view-portfolio" class="view">
        <div class="card">
          <div class="panel-title">
            <h3>持仓编辑</h3>
            <div class="actions"><button onclick="addRow()">新增</button><button class="primary" onclick="savePortfolio()">保存到本地</button></div>
          </div>
          <div class="portfolio-grid">
            <input id="userId" placeholder="user_id" />
            <input id="baseCurrency" placeholder="base currency" />
            <input id="cash" placeholder="cash" type="number" step="0.01" />
          </div>
          <div style="overflow:auto">
            <table>
              <thead><tr><th>代码</th><th>名称</th><th>行业</th><th>数量</th><th>总成本</th><th></th></tr></thead>
              <tbody id="positions"></tbody>
            </table>
          </div>
          <div id="portfolioToast" class="toast"></div>
        </div>
      </section>

      <section id="view-trades" class="view">
        <div class="grid metrics">
          <div class="card metric"><div class="label">交易记录</div><div id="tradeCount" class="value">-</div><div class="hint">all events</div></div>
          <div class="card metric"><div class="label">实现收益</div><div id="tradeRealizedPnl" class="value">-</div><div class="hint">sell P&L</div></div>
          <div class="card metric"><div class="label">未实现收益</div><div id="tradeUnrealizedPnl" class="value">-</div><div class="hint">current holdings</div></div>
          <div class="card metric"><div class="label">换手额</div><div id="tradeTurnover" class="value">-</div><div id="tradeWinRate" class="hint">win rate -</div></div>
        </div>

        <div class="grid workspace" style="margin-top:14px">
          <div class="card">
            <div class="panel-title"><h3>新增交易</h3><span class="pill">Buy / Sell / Dividend / Deposit / Withdraw</span></div>
            <div class="form-grid">
              <div class="form-field">
                <label for="tradeSide">类型</label>
                <select id="tradeSide" onchange="syncTradeFormMode()">
                  <option value="buy">Buy</option>
                  <option value="sell">Sell</option>
                  <option value="dividend">Dividend</option>
                  <option value="deposit">Deposit</option>
                  <option value="withdraw">Withdraw</option>
                </select>
              </div>
              <div class="form-field">
                <label for="tradeTime">时间</label>
                <input id="tradeTime" placeholder="留空使用当前时间" />
              </div>
              <div class="form-field trade-symbol-field">
                <label for="tradeSymbol">代码</label>
                <input id="tradeSymbol" placeholder="600519.SH / AAPL" />
              </div>
              <div class="form-field trade-symbol-field">
                <label for="tradeName">名称</label>
                <input id="tradeName" placeholder="可选" />
              </div>
              <div class="form-field trade-symbol-field">
                <label for="tradeSector">行业</label>
                <input id="tradeSector" placeholder="Technology / 消费" />
              </div>
              <div class="form-field trade-position-field">
                <label for="tradeQuantity">数量</label>
                <input id="tradeQuantity" type="number" step="0.0001" placeholder="shares / units" />
              </div>
              <div class="form-field trade-position-field">
                <label for="tradePrice">价格</label>
                <input id="tradePrice" type="number" step="0.0001" placeholder="trade price" />
              </div>
              <div class="form-field trade-cash-field">
                <label for="tradeAmount">现金金额</label>
                <input id="tradeAmount" type="number" step="0.01" placeholder="dividend / deposit / withdraw amount" />
              </div>
              <div class="form-field">
                <label for="tradeFees">费用</label>
                <input id="tradeFees" type="number" step="0.01" value="0" />
              </div>
              <div class="form-field full">
                <label for="tradeNote">投资记忆 / 交易理由</label>
                <input id="tradeNote" placeholder="例如：看好AI算力需求；止盈降低集中度" />
              </div>
            </div>
            <div class="actions" style="margin-top:14px"><button class="primary" onclick="submitTrade()">保存交易并更新持仓</button></div>
            <div id="tradeToast" class="toast"></div>
          </div>

          <div class="card">
            <div class="panel-title"><h3>交易闭环</h3><span class="pill ok">ledger</span></div>
            <div id="tradeLoopSummary" class="output" style="min-height:260px;max-height:360px">买入 → 交易记录 → 更新持仓 → 更新成本价 → 计算收益 → 行为分析</div>
          </div>
        </div>

        <div class="card" style="margin-top:14px">
          <div class="panel-title"><h3>Behavior Finance Profile</h3><span id="tradeProfileBadge" class="pill">profile</span></div>
          <div id="tradeProfilePanel"></div>
        </div>

        <div class="card" style="margin-top:14px">
          <div class="panel-title"><h3>Trade History</h3><span id="tradeLogPath" class="pill">local jsonl</span></div>
          <div style="overflow:auto">
            <table>
              <thead><tr><th>时间</th><th>类型</th><th>代码</th><th>数量</th><th>价格/金额</th><th>现金变化</th><th>实现收益</th><th>备注</th></tr></thead>
              <tbody id="tradeHistoryRows"></tbody>
            </table>
          </div>
        </div>
      </section>

      <section id="view-sources" class="view">
        <div class="grid workspace">
          <div class="card">
            <div class="panel-title"><h3>运行环境</h3><button onclick="runAction('config-show')">查看配置</button></div>
            <div class="section-label">项目路径</div>
            <div id="projectRoot" class="muted"></div>
            <div class="section-label" style="margin-top:14px">当前模型与市场数据</div>
            <div class="grid inline-metrics">
              <div class="inline-metric metric"><div class="label">市场数据</div><div id="sourceProvider" class="value">-</div><div id="sourceMode" class="hint">-</div></div>
              <div class="inline-metric metric"><div class="label">LLM</div><div id="sourceModel" class="value">-</div><div id="sourceModelName" class="hint">-</div></div>
            </div>
            <div id="sourceOutput" class="status-output" style="margin-top:14px">
              <div class="status-card">点击“查看配置”，这里会显示脱敏后的本地配置摘要。<small>密钥不会在界面回显。</small></div>
            </div>
          </div>
          <div class="card">
            <div class="panel-title"><h3>数据源能力</h3><span class="pill">providers</span></div>
            <div id="providers" class="provider-list"></div>
          </div>
        </div>
      </section>

      <section id="view-settings" class="view">
        <div class="grid settings-layout">
          <div class="stack">
            <div class="card settings-card">
              <div class="panel-title"><h3>通用设置</h3><span class="pill">preferences</span></div>
              <div class="form-grid">
                <div class="form-field">
                  <label for="appLanguage">Language</label>
                  <select id="appLanguage"></select>
                </div>
                <div class="form-field">
                  <label for="cachePolicy">Cache Policy</label>
                  <select id="cachePolicy"></select>
                </div>
                <div class="form-field full">
                  <label for="appTimezone">Time Zone</label>
                  <select id="appTimezone"></select>
                </div>
                <div class="form-field full">
                  <label>说明</label>
                  <div class="provider-note">
                    <div class="provider-note-row"><span>语言支持</span><strong>简中 / 繁中 / English / 日本語 / Français</strong></div>
                    <p class="muted" style="line-height:1.55;margin-top:4px">时区会影响总览页的昨日收益、本周收益、本月收益、YTD 和本周最大回撤。保存后回到总览页点击“刷新状态”即可按新时区重算。</p>
                  </div>
                </div>
              </div>
            </div>
            <div class="card settings-card">
              <div class="panel-title"><h3>模型配置</h3><span id="llmKeyState" class="pill">key unset</span></div>
              <div class="form-grid">
                <div class="form-field">
                  <label for="llmProvider">LLM Provider</label>
                  <select id="llmProvider" onchange="updateModelOptions()"></select>
                </div>
                <div class="form-field">
                  <label for="llmModel">Model</label>
                  <select id="llmModel"></select>
                </div>
                <div class="form-field full">
                  <label for="llmBaseUrl">Base URL</label>
                  <input id="llmBaseUrl" placeholder="默认或自定义 OpenAI-compatible endpoint" />
                </div>
                <div class="form-field full">
                  <label for="llmApiKey">API Key</label>
                  <div class="secret-row">
                    <input id="llmApiKey" type="password" placeholder="留空表示保留已有 key；输入新值会覆盖" />
                    <button onclick="clearSecret('llmApiKey')">清空</button>
                  </div>
                </div>
              </div>
            </div>

            <div class="card settings-card">
              <div class="panel-title"><h3>市场数据源配置</h3><span id="marketKeyState" class="pill">key unset</span></div>
              <div class="form-grid">
                <div class="form-field">
                  <label for="marketProvider">Market Provider</label>
                  <select id="marketProvider" onchange="renderMarketProviderHint()"></select>
                </div>
                <div class="form-field">
                  <label for="marketBaseUrl">Base URL</label>
                  <input id="marketBaseUrl" placeholder="通常留空" />
                </div>
                <div class="form-field full">
                  <label for="marketApiKey">API Key / Token</label>
                  <div class="secret-row">
                    <input id="marketApiKey" type="password" placeholder="Tushare token / provider API key；留空保留已有 key" />
                    <button onclick="clearSecret('marketApiKey')">清空</button>
                  </div>
                </div>
                <div class="form-field full">
                  <label>Provider Notes</label>
                  <div id="marketProviderHint" class="provider-note"></div>
                </div>
              </div>
            </div>
            <div class="card settings-card">
              <div class="panel-title"><h3>新闻源配置</h3><span class="pill">news</span></div>
              <div class="form-grid">
                <div class="form-field full">
                  <label for="newsProvider">News Source</label>
                  <select id="newsProvider" onchange="renderNewsProviderHint()"></select>
                </div>
                <div class="form-field full">
                  <label for="newsLookback">Default News Window</label>
                  <select id="newsLookback"></select>
                </div>
                <div class="form-field full">
                  <label>说明</label>
                  <div id="newsProviderHint" class="provider-note"></div>
                </div>
              </div>
            </div>
          </div>
          <div class="card settings-card">
            <div class="panel-title"><h3>保存配置</h3><span class="pill">local_config.json</span></div>
            <p class="settings-note">配置只写入本地私有文件。密钥不会在界面回显；输入框留空会保留已有 key，点击“清空”后保存则会移除。</p>
            <div class="config-summary">
              <div class="config-summary-item"><span>Model</span><strong id="configSummaryModel">-</strong></div>
              <div class="config-summary-item"><span>Market Data</span><strong id="configSummaryMarket">-</strong></div>
              <div class="config-summary-item"><span>Privacy</span><strong>Local only</strong></div>
            </div>
            <div class="actions" style="margin-top:16px">
              <button class="primary" onclick="saveRuntimeConfig()">保存配置</button>
              <button onclick="runAction('status')">验证状态</button>
              <button onclick="clearRuntimeCache()">清理缓存</button>
            </div>
            <div id="configToast" class="toast"></div>
            <div id="configOutput" class="status-output" style="margin-top:14px">
              <div class="status-card">保存后可以点击“验证状态”，这里会以状态摘要展示模型和数据源是否 ready。<small>不再直接展示杂乱命令行文本。</small></div>
            </div>
          </div>
        </div>
      </section>
    </main>
  </div>
  <script>
    let overview = null;
    let dashboard = null;
    let trades = null;
    let newsLookback = "7d";
    let currentView = "dashboard";

    const pageMeta = {
      dashboard: ["机构级组合风险终端", "Risk, exposure, liquidity and agent surveillance in a local-first operating layer."],
      daily: ["风险情报简报", "Generate a structured institutional briefing for portfolio risk and source provenance."],
      ask: ["组合情报控制台", "Query the portfolio intelligence layer for risk causes, exposures and action priority."],
      portfolio: ["持仓账本", "Maintain the local portfolio book used by the risk engine and intelligence console."],
      trades: ["交易行为账本", "Record trading events, realized P&L and behavior finance profile."],
      sources: ["数据与模型连接", "Monitor provider status, market data readiness and local configuration state."],
      settings: ["系统设置", "Govern language, models, data sources, news modules and local cache policy."]
    };

    const fmtMoney = (value, currency) => new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value || 0) + " " + (currency || "");
    const fmtPct = value => value === null || value === undefined ? "—" : (value * 100).toFixed(1) + "%";
    const fmtValue = value => value === null || value === undefined ? "—" : String(value);
    const fmtDays = value => value === null || value === undefined ? "样本不足" : Number(value).toFixed(1) + " 天";
    const fmtSignedMoney = (value, currency) => value === null || value === undefined ? "—" : (value >= 0 ? "+" : "") + fmtMoney(value, currency);
    const fmtDate = value => {
      if (!value) return "时间未知";
      const date = new Date(value);
      return Number.isNaN(date.getTime()) ? String(value).slice(0, 16) : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    };
    const escapeHtml = value => String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");

    function initAmbientBackground() {
      const canvas = document.getElementById("ambientCanvas");
      if (!canvas) return;
      const context = canvas.getContext("2d", { alpha: true });
      if (!context) return;
      const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      let width = 0;
      let height = 0;
      let dpr = 1;
      let rafId = 0;
      const palette = {
        gold: "212, 162, 76",
        amber: "139, 106, 43",
        emerald: "42, 174, 132",
        darkGreen: "26, 127, 100",
        risk: "127, 31, 31"
      };
      const particles = Array.from({ length: 34 }, (_, index) => ({
        seed: index * 97.31,
        x: Math.random(),
        y: Math.random(),
        speed: 0.000018 + Math.random() * 0.000028,
        radius: 0.8 + Math.random() * 1.8,
        hue: index % 5 === 0 ? palette.gold : index % 3 === 0 ? palette.emerald : palette.amber,
        alpha: 0.08 + Math.random() * 0.09
      }));

      function resizeAmbient() {
        dpr = Math.min(window.devicePixelRatio || 1, 1.6);
        width = Math.max(1, window.innerWidth);
        height = Math.max(1, window.innerHeight);
        canvas.width = Math.floor(width * dpr);
        canvas.height = Math.floor(height * dpr);
        canvas.style.width = width + "px";
        canvas.style.height = height + "px";
        context.setTransform(dpr, 0, 0, dpr, 0, 0);
      }

      function drawAurora(time) {
        const t = time * 0.000015;
        context.save();
        context.globalCompositeOperation = "screen";
        context.filter = `blur(${Math.max(32, Math.min(96, width * 0.045))}px)`;
        const bands = [
          { color: palette.gold, y: 0.34, amp: 0.10, alpha: 0.070, phase: 0 },
          { color: palette.emerald, y: 0.45, amp: 0.12, alpha: 0.058, phase: 2.2 },
          { color: palette.amber, y: 0.58, amp: 0.08, alpha: 0.046, phase: 4.1 },
          { color: palette.risk, y: 0.82, amp: 0.08, alpha: 0.042, phase: 1.2 }
        ];
        bands.forEach((band, index) => {
          const gradient = context.createLinearGradient(0, height * (band.y - .18), width, height * (band.y + .18));
          gradient.addColorStop(0, `rgba(${band.color},0)`);
          gradient.addColorStop(.42, `rgba(${band.color},${band.alpha})`);
          gradient.addColorStop(1, `rgba(${band.color},0)`);
          context.beginPath();
          const startY = height * (band.y + Math.sin(t + band.phase) * 0.025);
          context.moveTo(-width * .08, startY);
          for (let step = 0; step <= 8; step += 1) {
            const x = (step / 8) * width;
            const wave = Math.sin(t * (1.2 + index * .16) + band.phase + step * .78) * height * band.amp;
            const drift = Math.cos(t * .72 + step * .52 + index) * height * .026;
            context.lineTo(x, height * band.y + wave + drift);
          }
          context.lineTo(width * 1.08, height * (band.y + .22));
          context.lineTo(-width * .08, height * (band.y + .22));
          context.closePath();
          context.fillStyle = gradient;
          context.fill();
        });
        context.restore();
      }

      function drawParticles(time) {
        const t = time * 0.001;
        context.save();
        context.globalCompositeOperation = "screen";
        context.filter = "blur(.2px)";
        particles.forEach((particle, index) => {
          const flow = (t * particle.speed + particle.seed) % 1;
          const x = ((particle.x + flow * 0.24 + Math.sin(t * 0.010 + particle.seed) * 0.018) % 1) * width;
          const y = ((particle.y + Math.sin(t * 0.006 + particle.seed * .3) * 0.055 + Math.cos(t * 0.004 + index) * 0.022) % 1) * height;
          const radius = particle.radius * (1 + Math.sin(t * 0.018 + particle.seed) * .22);
          const tail = 28 + radius * 8;
          const gradient = context.createLinearGradient(x - tail, y, x + tail, y);
          gradient.addColorStop(0, `rgba(${particle.hue},0)`);
          gradient.addColorStop(.5, `rgba(${particle.hue},${particle.alpha})`);
          gradient.addColorStop(1, `rgba(${particle.hue},0)`);
          context.strokeStyle = gradient;
          context.lineWidth = Math.max(0.45, radius * .65);
          context.beginPath();
          context.moveTo(x - tail, y);
          context.quadraticCurveTo(x, y + Math.sin(t * .01 + index) * 7, x + tail, y);
          context.stroke();
          context.beginPath();
          context.fillStyle = `rgba(${particle.hue},${particle.alpha * 1.4})`;
          context.arc(x, y, radius, 0, Math.PI * 2);
          context.fill();
        });
        context.restore();
      }

      function renderAmbient(time) {
        context.clearRect(0, 0, width, height);
        context.fillStyle = "rgba(5,5,5,0.10)";
        context.fillRect(0, 0, width, height);
        drawAurora(time);
        drawParticles(time);
        if (!reduceMotion) rafId = window.requestAnimationFrame(renderAmbient);
      }

      resizeAmbient();
      window.addEventListener("resize", resizeAmbient, { passive: true });
      renderAmbient(0);
      if (!reduceMotion) rafId = window.requestAnimationFrame(renderAmbient);
      window.addEventListener("beforeunload", () => window.cancelAnimationFrame(rafId));
    }

    async function api(path, options = {}) {
      const response = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        ...options
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "Request failed");
      return data;
    }

    function setBusy(label) {
      document.getElementById("runState").textContent = label;
      document.querySelectorAll("button").forEach(button => button.disabled = true);
    }

    function clearBusy(label = "ready") {
      document.getElementById("runState").textContent = label;
      document.querySelectorAll("button").forEach(button => button.disabled = false);
    }

    function showView(name) {
      currentView = name;
      document.querySelectorAll(".view").forEach(view => view.classList.remove("active"));
      document.getElementById("view-" + name).classList.add("active");
      document.querySelectorAll("nav button").forEach(button => button.classList.toggle("active", button.dataset.view === name));
      document.getElementById("pageTitle").textContent = pageMeta[name][0];
      document.getElementById("pageSubtitle").textContent = pageMeta[name][1];
    }

    function commandOutputTarget() {
      if (currentView === "daily") return document.getElementById("dailyOutput");
      if (currentView === "sources") return document.getElementById("sourceOutput");
      if (currentView === "settings") return document.getElementById("configOutput");
      return document.getElementById("riskSummaryPanel");
    }

    async function loadOverview() {
      overview = await api("/api/overview");
      document.documentElement.lang = overview.config.app?.language || "zh-CN";
      if (overview.setup?.required) {
        renderSetupForms();
        document.body.classList.add("setup-required");
        return;
      }
      document.body.classList.remove("setup-required");
      dashboard = await api("/api/dashboard");
      trades = await api("/api/trades");
      newsLookback = dashboard.news?.lookback || overview.config.news?.lookback || "7d";
      renderOverview();
      renderDashboard();
      renderTrades();
      renderPortfolio(overview.portfolio);
      renderProviders(overview.providers, overview.config.market_data.provider);
      renderConfigForms();
    }

    function renderOverview() {
      const portfolio = overview.portfolio;
      const positions = portfolio.positions || [];
      document.getElementById("sideProvider").textContent = overview.config.market_data.provider;
      document.getElementById("sideModel").textContent = overview.config.llm.provider;
      document.getElementById("sidePositions").textContent = String(positions.length);
      document.getElementById("projectRoot").textContent = overview.project_root;
      document.getElementById("sourceProvider").textContent = overview.config.market_data.provider;
      document.getElementById("sourceMode").textContent = overview.config.market_data.mode || "mode unknown";
      document.getElementById("sourceModel").textContent = overview.config.llm.provider;
      document.getElementById("sourceModelName").textContent = overview.config.llm.model;
      document.getElementById("configSummaryModel").textContent = `${overview.config.llm.provider} · ${overview.config.llm.model || "default"}`;
      document.getElementById("configSummaryMarket").textContent = `${overview.config.market_data.provider} · news ${overview.config.news?.provider || "auto"}`;
      const secrets = overview.config._secrets || {};
      document.getElementById("llmKeyState").textContent = secrets.llm_api_key_set ? "key set" : "key unset";
      document.getElementById("llmKeyState").className = "pill " + (secrets.llm_api_key_set ? "ok" : "warn");
      document.getElementById("marketKeyState").textContent = secrets.market_api_key_set ? "key set" : "key unset";
      document.getElementById("marketKeyState").className = "pill " + (secrets.market_api_key_set ? "ok" : "warn");
    }

    function colorClass(value) {
      if (value === null || value === undefined) return "";
      return value >= 0 ? "positive" : "negative";
    }

    function setMetric(id, value, className = "") {
      const el = document.getElementById(id);
      el.className = "value " + className;
      el.replaceChildren();
      const text = String(value ?? "—");
      const amountMatch = text.match(/^([+-]?[0-9][0-9,]*(?:\.[0-9]+)?)\s+([A-Z]{2,6})$/);
      if (amountMatch) {
        const number = document.createElement("span");
        number.className = "amount-number";
        number.textContent = amountMatch[1];
        const currency = document.createElement("span");
        currency.className = "amount-currency";
        currency.textContent = amountMatch[2];
        el.append(number, currency);
        return;
      }
      el.textContent = text;
    }

    function renderDashboard() {
      if (!dashboard) return;
      const m = dashboard.metrics || {};
      const currency = dashboard.base_currency || "USD";
      const history = dashboard.market_history || {};
      const time = dashboard.time || {};
      const historyOk = (history.ok_symbols || []).length > 0;
      const firstHistoryError = Object.values(history.errors || {})[0];
      const cachePart = history.cache ? ` · snapshot ${history.cache}` : "";
      const historyHint = historyOk
        ? `${history.provider || "provider"} · ${history.history_points || 0} points · ${history.ok_symbols.length} symbols${cachePart}`
        : `${history.provider || "provider"} · ${firstHistoryError || "history unavailable"}${cachePart}`;
      document.getElementById("dashTimezone").textContent = `${time.local_date || "-"} ${time.local_time || ""}「${time.timezone_label || time.timezone || "北京时间"}」`;
      document.getElementById("dashTodayBoundary").textContent = `${time.latest_market_date || "-"} · cutoff ${time.cutoff_date || "-"}`;
      document.getElementById("dashWeekBoundary").textContent = time.week_start || "-";
      document.getElementById("dashMonthBoundary").textContent = `${time.month_start || "-"} / ${time.ytd_start || "-"}`;
      setMetric("dashTotalAssets", fmtMoney(m.total_assets, currency));
      document.getElementById("dashCash").textContent = "cash " + fmtMoney(m.cash, currency);
      setMetric("dashTodayPnl", fmtSignedMoney(m.today_pnl, currency), colorClass(m.today_pnl));
      document.getElementById("dashTodayReturn").textContent = (dashboard.periods?.today?.status || "unknown") + " · " + fmtPct(m.today_return);
      setMetric("dashWeekReturn", fmtSignedMoney(m.week_pnl, currency), colorClass(m.week_pnl));
      document.getElementById("dashWeekHint").textContent = (dashboard.periods?.week?.status || "unknown") + " · " + fmtPct(m.week_return);
      setMetric("dashMonthReturn", fmtSignedMoney(m.month_pnl, currency), colorClass(m.month_pnl));
      document.getElementById("dashMonthHint").textContent = (dashboard.periods?.month?.status || "unknown") + " · " + fmtPct(m.month_return);
      setMetric("dashYtdReturn", fmtSignedMoney(m.ytd_pnl, currency), colorClass(m.ytd_pnl));
      document.getElementById("dashUnrealized").textContent = (dashboard.periods?.ytd?.status || "unknown") + " · " + fmtPct(m.ytd_return);
      setMetric("dashRiskLevel", m.risk_level || "—", "risk-" + String(m.risk_level || "").toLowerCase());
      document.getElementById("dashRiskScore").textContent = "score " + fmtValue(m.risk_score);
      setMetric("dashMaxDrawdown", fmtPct(m.max_drawdown));
      document.getElementById("dashDrawdownHint").textContent = historyHint;
      setMetric("dashVolatility", fmtPct(m.volatility));
      document.getElementById("dashVolHint").textContent = historyHint;
      setMetric("dashSharpe", fmtValue(m.sharpe_ratio));
      document.getElementById("dashSharpeHint").textContent = historyHint;
      setMetric("dashCashRatio", fmtPct(m.cash_ratio));
      document.getElementById("dashLargestWeight").textContent = "largest " + fmtPct(m.largest_position_weight);
      document.getElementById("dashProfile").textContent = `${dashboard.profile?.risk_profile || "Risk"} · ${dashboard.profile?.behavior_profile || "Profile"}`;
      document.getElementById("profileConfidence").textContent = `confidence ${dashboard.profile?.confidence || "—"}`;

      renderRiskCommand(dashboard, currency);
      renderPnlCalendar(dashboard.calendar || {}, currency);
      renderAllocationChart(dashboard.allocation || [], currency);
      renderHoldingWeights(dashboard.holdings || []);
      renderExposureChart(dashboard.exposures || []);
      renderRiskSummary(dashboard.summary || {});
      renderAlerts(dashboard.alerts || []);
      renderInvestorProfile("investorProfilePanel", dashboard.profile || {});
      renderOptimization(dashboard.optimization || []);
      renderNews(dashboard.news || {});
    }

    function renderPnlCalendar(calendar, currency) {
      const target = document.getElementById("pnlCalendar");
      const month = calendar.month || "";
      document.getElementById("calendarMonth").textContent = month || "calendar";
      if (!target) return;
      const days = calendar.days || [];
      if (!month || !days.length) {
        target.innerHTML = `<div class="news-empty" style="grid-column:1/-1">暂无月度交易日盈亏数据。需要市场数据源返回本月历史收盘价。</div>`;
        return;
      }
      const [year, monthNumber] = month.split("-").map(Number);
      const firstDay = new Date(year, monthNumber - 1, 1);
      const daysInMonth = new Date(year, monthNumber, 0).getDate();
      const offset = firstDay.getDay() === 0 ? 6 : firstDay.getDay() - 1;
      const byDay = new Map(days.map(item => [Number(item.day), item]));
      const headers = ["一", "二", "三", "四", "五", "六", "日"].map(label => `<div class="calendar-cell header">${label}</div>`);
      const cells = [];
      for (let i = 0; i < offset; i += 1) cells.push(`<div class="calendar-cell empty"></div>`);
      for (let day = 1; day <= daysInMonth; day += 1) {
        const item = byDay.get(day);
        if (!item) {
          cells.push(`<div class="calendar-cell"><div class="day-num">${day}</div><div>无交易</div></div>`);
          continue;
        }
        const cls = item.pnl > 0 ? "positive" : item.pnl < 0 ? "negative" : "";
        cells.push(`
          <div class="calendar-cell ${cls}">
            <div class="day-num">${day}</div>
            <div class="pnl">${fmtSignedMoney(item.pnl, currency)}</div>
            <div>${fmtPct(item.return)}</div>
          </div>
        `);
      }
      target.innerHTML = headers.concat(cells).join("");
    }

    async function refreshDashboardData() {
      setBusy("refreshing market history");
      try {
        dashboard = await api("/api/dashboard");
        trades = await api("/api/trades");
        renderDashboard();
        renderTrades();
        clearBusy("done");
      } catch (error) {
        document.getElementById("riskSummaryPanel").innerHTML = `<div class="status-card">刷新失败<small>${escapeHtml(error.message)}</small></div>`;
        clearBusy("failed");
      }
    }

    async function refreshNews() {
      setBusy("refreshing news");
      try {
        const news = await api("/api/news?lookback=" + encodeURIComponent(newsLookback));
        dashboard.news = news;
        renderNews(news);
        clearBusy("done");
      } catch (error) {
        document.getElementById("portfolioNewsList").innerHTML = `<div class="news-empty">新闻刷新失败：${escapeHtml(error.message)}</div>`;
        clearBusy("failed");
      }
    }

    async function setNewsLookback(lookback) {
      newsLookback = lookback;
      await refreshNews();
    }

    function renderTrades() {
      if (!trades) return;
      const summary = trades.summary || {};
      const currency = dashboard?.base_currency || overview?.portfolio?.base_currency || "";
      setMetric("tradeCount", String(summary.trade_count || 0));
      setMetric("tradeRealizedPnl", fmtMoney(summary.realized_pnl, currency), colorClass(summary.realized_pnl));
      setMetric("tradeUnrealizedPnl", fmtMoney(summary.unrealized_pnl, currency), colorClass(summary.unrealized_pnl));
      setMetric("tradeTurnover", fmtMoney(summary.turnover, currency));
      document.getElementById("tradeWinRate").textContent = "win rate " + fmtPct(summary.win_rate);
      document.getElementById("tradeLogPath").textContent = trades.log_path || "local jsonl";
      document.getElementById("tradeLoopSummary").textContent = [
        "交易记录: " + (summary.trade_count || 0),
        "Buy: " + (summary.buys || 0) + " / Sell: " + (summary.sells || 0),
        "Dividend: " + fmtMoney(summary.dividends || 0, currency),
        "Deposit: " + fmtMoney(summary.deposits || 0, currency),
        "Withdraw: " + fmtMoney(summary.withdrawals || 0, currency),
        "Realized P&L: " + fmtMoney(summary.realized_pnl || 0, currency),
        "Turnover: " + fmtPct((trades.profile || dashboard?.profile || {}).turnover_rate),
        "Average Holding: " + fmtDays((trades.profile || dashboard?.profile || {}).avg_holding_period),
        "",
        "画像来源：交易日志 + 当前持仓结构。记录投资理由越完整，Agent 的行为判断越稳定。"
      ].join("\n");
      const profile = trades.profile || dashboard?.profile || {};
      document.getElementById("tradeProfileBadge").textContent = `${profile.risk_profile || "Risk"} · ${profile.confidence || "—"}`;
      renderInvestorProfile("tradeProfilePanel", profile);
      const rows = document.getElementById("tradeHistoryRows");
      rows.innerHTML = (trades.entries || []).map(entry => {
        const trade = entry.trade || {};
        const amount = ["dividend", "deposit", "withdraw"].includes(trade.side)
          ? fmtMoney(trade.amount, currency)
          : `${trade.quantity || ""} @ ${trade.price || ""}`;
        return `<tr>
          <td>${trade.traded_at || entry.recorded_at || ""}</td>
          <td>${trade.side || ""}</td>
          <td>${trade.symbol || "CASH"}</td>
          <td>${trade.quantity || ""}</td>
          <td>${amount}</td>
          <td>${fmtMoney(entry.cash_delta || 0, currency)}</td>
          <td>${fmtMoney(entry.realized_pnl || 0, currency)}</td>
          <td>${trade.note || ""}</td>
        </tr>`;
      }).join("") || `<tr><td colspan="8" class="muted">暂无交易记录。新增一笔交易后会显示在这里。</td></tr>`;
      syncTradeFormMode();
    }

    function syncTradeFormMode() {
      const side = document.getElementById("tradeSide")?.value || "buy";
      const cashMode = ["deposit", "withdraw"].includes(side);
      const cashEvent = ["dividend", "deposit", "withdraw"].includes(side);
      document.querySelectorAll(".trade-position-field").forEach(el => el.style.display = cashEvent ? "none" : "grid");
      document.querySelectorAll(".trade-cash-field").forEach(el => el.style.display = cashEvent ? "grid" : "none");
      document.querySelectorAll(".trade-symbol-field").forEach(el => el.style.display = cashMode ? "none" : "grid");
    }

    function collectTrade() {
      return {
        side: document.getElementById("tradeSide").value,
        traded_at: document.getElementById("tradeTime").value,
        symbol: document.getElementById("tradeSymbol").value,
        name: document.getElementById("tradeName").value,
        sector: document.getElementById("tradeSector").value,
        quantity: document.getElementById("tradeQuantity").value,
        price: document.getElementById("tradePrice").value,
        amount: document.getElementById("tradeAmount").value,
        fees: document.getElementById("tradeFees").value || "0",
        note: document.getElementById("tradeNote").value
      };
    }

    async function submitTrade() {
      const toast = document.getElementById("tradeToast");
      toast.textContent = "保存交易中...";
      try {
        const result = await api("/api/trades", { method: "POST", body: JSON.stringify({ trade: collectTrade() }) });
        trades = result.trades;
        overview.portfolio = result.portfolio;
        dashboard = result.dashboard;
        renderDashboard();
        renderTrades();
        renderPortfolio(overview.portfolio);
        toast.textContent = "交易已保存，持仓和现金已更新。";
      } catch (error) {
        toast.textContent = error.message;
      }
    }

    function riskColor(score, index = 0) {
      const value = Number(score || 0);
      if (value >= 72) return "#7f1f1f";
      if (value >= 46) return "#d4a24c";
      if (value >= 24) return "#8b6a2b";
      return ["#2aae84", "#1a7f64", "#6f5a2b"][index % 3];
    }

    function normalizeRiskScore(value, fallback = 0) {
      const num = Number(value);
      if (!Number.isFinite(num)) return fallback;
      return Math.max(0, Math.min(100, num));
    }

    function buildRiskFactors(data) {
      const m = data.metrics || {};
      const factors = [];
      (data.exposures || []).forEach(item => {
        factors.push({
          name: item.name || "Exposure",
          score: normalizeRiskScore(item.score),
          detail: "主题/行业暴露"
        });
      });
      if (m.largest_position_weight !== null && m.largest_position_weight !== undefined) {
        factors.push({
          name: "最大持仓",
          score: normalizeRiskScore(Number(m.largest_position_weight || 0) * 100),
          detail: "单一仓位集中度"
        });
      }
      if (m.cash_ratio !== null && m.cash_ratio !== undefined) {
        const cashRatio = Number(m.cash_ratio || 0);
        const cashRisk = cashRatio < .1 ? (0.1 - cashRatio) / .1 * 100 : Math.max(0, 34 - cashRatio * 100);
        factors.push({
          name: "现金缓冲",
          score: normalizeRiskScore(cashRisk),
          detail: "低现金流动性风险"
        });
      }
      if (m.volatility !== null && m.volatility !== undefined) {
        factors.push({
          name: "波动率",
          score: normalizeRiskScore(Number(m.volatility || 0) * 260),
          detail: "历史净值波动"
        });
      }
      if (m.max_drawdown !== null && m.max_drawdown !== undefined) {
        factors.push({
          name: "回撤",
          score: normalizeRiskScore(Math.abs(Number(m.max_drawdown || 0)) * 420),
          detail: "历史最大回撤"
        });
      }
      if (m.sharpe_ratio !== null && m.sharpe_ratio !== undefined) {
        const sharpe = Number(m.sharpe_ratio);
        const sharpeRisk = sharpe >= 1 ? 18 : sharpe >= 0 ? 46 - sharpe * 20 : 76;
        factors.push({
          name: "收益质量",
          score: normalizeRiskScore(sharpeRisk),
          detail: "Sharpe 越低风险越高"
        });
      }
      return factors
        .filter(item => item.name && Number.isFinite(item.score))
        .sort((a, b) => b.score - a.score)
        .slice(0, 6);
    }

    function riskNarrative(level, factors, alerts) {
      const topFactor = factors[0]?.name || "组合结构";
      const topAlert = alerts[0]?.title;
      if (!factors.length && !alerts.length) return "当前缺少足够的行情或持仓细节，风险中枢会在数据补齐后显示集中度、暴露和回撤压力。";
      return `今日组合风险核心来自「${topFactor}」${topAlert ? `，Agent 首要关注「${topAlert}」` : ""}。先看风险，再看收益，避免被单日涨跌带偏。`;
    }

    function renderSystemStatusItem(id, state, detail) {
      const target = document.getElementById(id);
      if (!target) return;
      target.classList.remove("ok", "warn", "muted");
      target.classList.add(state || "muted");
      const detailTarget = target.querySelector("small");
      if (detailTarget) detailTarget.textContent = detail || "-";
    }

    function renderSystemStatus(data) {
      const history = data.market_history || {};
      const news = data.news || {};
      const newsStatus = news.status || {};
      const time = data.time || {};
      const historyOk = (history.ok_symbols || []).length > 0;
      const riskReady = data.metrics?.risk_score !== null && data.metrics?.risk_score !== undefined;
      const newsCount = Number(newsStatus.item_count || (news.items || []).length || 0);
      const newsProvider = newsStatus.provider || news.provider || overview?.config?.news?.provider || "auto";
      renderSystemStatusItem("statusPortfolioEngine", "ok", `${(overview?.portfolio?.positions || []).length} positions loaded`);
      renderSystemStatusItem(
        "statusMarketData",
        historyOk ? "ok" : "warn",
        historyOk ? `${history.provider || "provider"} · ${history.ok_symbols.length} symbols` : `${history.provider || "provider"} · fallback`
      );
      renderSystemStatusItem(
        "statusNewsEngine",
        newsCount > 0 ? "ok" : "warn",
        `${newsProvider} · ${newsCount} mapped`
      );
      renderSystemStatusItem(
        "statusRiskUpdated",
        riskReady ? "ok" : "muted",
        `${time.local_date || "-"} ${time.local_time || ""}`.trim()
      );
    }

    function renderRiskCommand(data, currency) {
      const m = data.metrics || {};
      const factors = buildRiskFactors(data);
      const alerts = data.alerts || [];
      const level = m.risk_level || "—";
      const riskHeroLevel = document.getElementById("riskHeroLevel");
      riskHeroLevel.textContent = level;
      riskHeroLevel.className = "risk-" + String(level).toLowerCase();
      document.getElementById("riskHeroScoreValue").textContent = fmtValue(m.risk_score);
      document.getElementById("riskHeroScore").textContent = "score " + fmtValue(m.risk_score);
      document.getElementById("riskHeroNarrative").textContent = riskNarrative(level, factors, alerts);
      const pulses = [
        `最大持仓 ${fmtPct(m.largest_position_weight)}`,
        `现金 ${fmtPct(m.cash_ratio)}`,
        `波动率 ${fmtPct(m.volatility)}`,
        `回撤 ${fmtPct(m.max_drawdown)}`
      ];
      document.getElementById("riskPulseList").innerHTML = pulses.map(item => `<span class="risk-chip">${item}</span>`).join("");
      renderSystemStatus(data);
      renderRiskHistogram(factors);
      renderRiskRadial(factors, m.risk_score);
    }

    function renderRiskHistogram(factors) {
      const target = document.getElementById("riskHistogram");
      if (!factors.length) {
        target.innerHTML = `<div class="news-empty" style="grid-column:1/-1">暂无可计算风险因子。补齐行情历史、行业标签或持仓权重后会自动生成直方图。</div>`;
        return;
      }
      target.innerHTML = factors.map((item, index) => {
        const height = Math.max(5, Math.min(100, item.score));
        return `
          <div class="risk-bar" title="${escapeHtml(item.detail || "")}">
            <div class="risk-bar-column"><div class="risk-bar-fill" style="height:${height}%; background:linear-gradient(180deg, ${riskColor(item.score, index)}, #d4a24c 64%, #2aae84)"></div></div>
            <strong>${escapeHtml(item.name)}</strong>
            <span>${item.score.toFixed(0)}</span>
          </div>
        `;
      }).join("");
    }

    function renderRiskRadial(factors, riskScore) {
      const target = document.getElementById("riskRadial");
      if (!factors.length) {
        target.innerHTML = `<div class="news-empty">暂无风险扇形图数据。</div>`;
        return;
      }
      const gradients = factors.map((item, index) => `
        <linearGradient id="riskGrad${index}" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0%" stop-color="${riskColor(item.score, index)}" stop-opacity=".98"></stop>
          <stop offset="62%" stop-color="#d4a24c" stop-opacity=".86"></stop>
          <stop offset="100%" stop-color="#2aae84" stop-opacity=".78"></stop>
        </linearGradient>
      `).join("");
      const total = factors.reduce((sum, item) => sum + Math.max(1, item.score), 0) || 1;
      let angle = 0;
      const slices = factors.map((item, index) => {
        const portion = Math.max(1, item.score) / total;
        const end = angle + portion * 360;
        const path = `<path d="${describeArc(90, 90, 76, angle, end)}" fill="url(#riskGrad${index})" opacity=".92"></path>`;
        angle = end;
        return path;
      }).join("");
      const legend = factors.map((item, index) => `
        <div class="risk-factor"><span style="background:${riskColor(item.score, index)}"></span><span>${escapeHtml(item.name)}</span><strong>${item.score.toFixed(0)}</strong></div>
      `).join("");
      target.innerHTML = `
        <svg width="180" height="180" viewBox="0 0 180 180" aria-label="risk factor pie">
          <defs>${gradients}</defs>
          ${slices}
          <circle cx="90" cy="90" r="44" fill="rgba(5,5,5,.78)" stroke="rgba(212,162,76,.18)"></circle>
          <text x="90" y="86" text-anchor="middle" class="risk-radial-center">Risk</text>
          <text x="90" y="108" text-anchor="middle" fill="#9b9385" font-size="16" font-weight="700">${fmtValue(riskScore)}</text>
        </svg>
        <div class="risk-factor-list">${legend}</div>
      `;
    }

    function chartColor(index) {
      return ["#d4a24c", "#1a7f64", "#8b6a2b", "#2aae84", "#7f1f1f", "#6b6255", "#b88435"][index % 7];
    }

    function polarToCartesian(cx, cy, r, angle) {
      const rad = (angle - 90) * Math.PI / 180;
      return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
    }

    function describeArc(cx, cy, r, startAngle, endAngle) {
      const [sx, sy] = polarToCartesian(cx, cy, r, endAngle);
      const [ex, ey] = polarToCartesian(cx, cy, r, startAngle);
      const largeArc = endAngle - startAngle <= 180 ? "0" : "1";
      return `M ${cx} ${cy} L ${sx} ${sy} A ${r} ${r} 0 ${largeArc} 0 ${ex} ${ey} Z`;
    }

    function renderAllocationChart(items, currency) {
      const target = document.getElementById("allocationChart");
      const slices = [];
      const gradients = items.map((item, index) => `
        <linearGradient id="allocGrad${index}" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0%" stop-color="${chartColor(index)}" stop-opacity=".98"></stop>
          <stop offset="64%" stop-color="#d4a24c" stop-opacity=".82"></stop>
          <stop offset="100%" stop-color="#1a7f64" stop-opacity=".76"></stop>
        </linearGradient>
      `).join("");
      let angle = 0;
      items.forEach((item, index) => {
        const weight = Number(item.weight || 0);
        const end = angle + weight * 360;
        if (weight > 0) {
          slices.push(`<path d="${describeArc(90, 90, 76, angle, end)}" fill="url(#allocGrad${index})" opacity=".92"></path>`);
        }
        angle = end;
      });
      const legend = items.map((item, index) => `
        <div class="legend-row"><span class="legend-dot" style="background:${chartColor(index)}"></span><span>${item.name}</span><span>${fmtPct(item.weight)}</span></div>
      `).join("");
      target.innerHTML = `
        <svg width="180" height="180" viewBox="0 0 180 180" aria-label="asset allocation"><defs>${gradients}</defs>${slices.join("")}<circle cx="90" cy="90" r="42" fill="rgba(5,5,5,.78)" stroke="rgba(212,162,76,.18)"></circle></svg>
        <div class="legend">${legend}</div>
      `;
    }

    function renderHoldingWeights(items) {
      document.getElementById("holdingWeightChart").innerHTML = items.slice(0, 8).map(item => `
        <div class="bar-row">
          <div class="bar-head"><span>${item.symbol} · ${item.name || ""}</span><span>${fmtPct(item.weight)}</span></div>
          <div class="bar-track"><div class="bar-fill" style="width:${Math.max(1, Number(item.weight || 0) * 100)}%"></div></div>
        </div>
      `).join("");
    }

    function renderExposureChart(items) {
      document.getElementById("exposureChart").innerHTML = items.map(item => `
        <div class="bar-row">
          <div class="bar-head"><span>${item.name}</span><span>${Number(item.score || 0).toFixed(1)}</span></div>
          <div class="bar-track"><div class="bar-fill" style="width:${Math.max(1, Number(item.score || 0))}%"></div></div>
        </div>
      `).join("");
    }

    function renderRiskSummary(summary) {
      const risks = (summary.main_risks || []).map(item => `<li>${item}</li>`).join("");
      const opportunities = (summary.main_opportunities || []).map(item => `<li>${item}</li>`).join("");
      const themes = (summary.theme_changes || []).map(item => `<li>${item}</li>`).join("");
      document.getElementById("riskSummaryPanel").innerHTML = `
        <div class="metric"><div class="label">Risk Level</div><div class="value risk-${String(summary.risk_level || "").toLowerCase()}">${summary.risk_level || "—"}</div></div>
        <div class="section-label" style="margin-top:14px">主要风险</div><ul class="muted">${risks}</ul>
        <div class="section-label">主要机会</div><ul class="muted">${opportunities}</ul>
        <div class="section-label">主题变化</div><ul class="muted">${themes}</ul>
        <div class="section-label">Agent Action</div><p class="muted">${summary.agent_action || "继续监控"}</p>
      `;
    }

    function renderAlerts(items) {
      document.getElementById("agentAlerts").innerHTML = items.map(item => `
        <div class="alert-item"><strong class="risk-${item.severity === "high" ? "high" : item.severity === "medium" ? "medium" : "low"}">${item.title}</strong><p>${item.detail}</p></div>
      `).join("");
    }

    function renderInvestorProfile(targetId, profile) {
      const dimensions = (profile.dimensions || []).map(item => {
        const score = item.score === null || item.score === undefined ? null : Number(item.score);
        const width = score === null ? 0 : Math.max(0, Math.min(100, score));
        return `
          <div class="profile-row">
            <div class="bar-head"><span>${item.name}</span><span>${score === null ? "样本不足" : score.toFixed(1)}</span></div>
            <div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div>
            <div class="muted" style="font-size:11px">${item.detail || ""}</div>
          </div>
        `;
      }).join("");
      const observations = (profile.observations || []).map(item => `<div>${item}</div>`).join("");
      document.getElementById(targetId).innerHTML = `
        <div class="profile-head">
          <div class="profile-tile"><span>Risk Profile</span><strong>${profile.risk_profile || "—"}</strong></div>
          <div class="profile-tile"><span>Behavior Profile</span><strong>${profile.behavior_profile || "—"}</strong></div>
          <div class="profile-tile"><span>Turnover</span><strong>${fmtPct(profile.turnover_rate)}</strong></div>
          <div class="profile-tile"><span>Avg Holding</span><strong>${fmtDays(profile.avg_holding_period)}</strong></div>
        </div>
        <div class="profile-list">${dimensions || `<div class="muted">暂无画像分数。</div>`}</div>
        <div class="profile-observations">${observations}</div>
      `;
    }

    function renderOptimization(items) {
      document.getElementById("optimizationList").innerHTML = items.map(item => `
        <div class="suggestion-item"><strong>${item.title}</strong><p>${item.current} → ${item.target}</p><p>${item.rationale}</p></div>
      `).join("");
    }

    function renderNews(news) {
      const status = news.status || {};
      const items = news.items || [];
      const errors = status.errors || [];
      const adapter = status.adapter ? ` via ${status.adapter}` : "";
      const fallback = status.fallback_used ? " · fallback" : "";
      newsLookback = news.lookback || newsLookback || "7d";
      document.querySelectorAll("[data-news-lookback]").forEach(button => {
        button.classList.toggle("active", button.dataset.newsLookback === newsLookback);
      });
      document.getElementById("newsStatus").textContent = `${news.provider || "news"}${adapter}${fallback} · ${status.status || "unknown"}`;
      document.getElementById("newsStatus").className = "pill " + (items.length ? "ok" : "warn");
      const target = document.getElementById("portfolioNewsList");
      if (!items.length) {
        const reason = errors[0] || "最近没有匹配到持仓相关新闻。";
        target.innerHTML = `
          <div class="news-empty">
            暂无组合相关新闻。<br />
            当前状态：${escapeHtml(status.status || "unknown")}；原因：${escapeHtml(reason)}<br />
            已做通用适配：优先使用当前数据源的新闻能力；若没有专用新闻接口，会尝试 Yahoo Finance 新闻 fallback。建议检查数据源 token、账号权限，以及持仓代码是否为 600519.SH / AAPL 这类标准格式。
          </div>
        `;
        return;
      }
      target.innerHTML = items.map(item => {
        const symbols = (item.symbols || []).map(symbol => `<span class="pill">${escapeHtml(symbol)}</span>`).join("");
        const title = escapeHtml(item.title || "未命名新闻");
        const titleHtml = item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">${title}</a>` : title;
        return `
          <div class="news-item">
            <div class="news-meta"><span>${escapeHtml(item.source || "tushare")}</span><span>${fmtDate(item.timestamp)}</span></div>
            <strong>${titleHtml}</strong>
            <p>${escapeHtml(item.summary || "暂无摘要")}</p>
            <div class="news-symbols">${symbols}</div>
          </div>
        `;
      }).join("");
    }

    function optionLabel(key, meta) {
      const label = meta && meta.label ? meta.label : key;
      const status = meta && meta.status ? " · " + meta.status : "";
      return key + " · " + label + status;
    }

    function fillSelect(select, entries, active) {
      select.innerHTML = "";
      Object.entries(entries || {}).forEach(([key, meta]) => {
        const option = document.createElement("option");
        option.value = key;
        option.textContent = optionLabel(key, meta);
        option.selected = key === active;
        select.appendChild(option);
      });
    }

    function renderSetupForms() {
      const options = overview.options || {};
      fillSelect(document.getElementById("setupLanguage"), options.languages || {}, overview.config.app?.language || "zh-CN");
      fillSelect(document.getElementById("setupCachePolicy"), options.cache_policies || {}, overview.config.app?.cache_policy || "standard");
      fillSelect(document.getElementById("setupTimezone"), options.timezones || {}, overview.config.app?.timezone || "Asia/Shanghai");
      fillSelect(document.getElementById("setupLlmProvider"), options.llm_models || {}, overview.config.llm.provider || "local_template");
      updateSetupModelOptions(false);
      document.getElementById("setupLlmBaseUrl").value = overview.config.llm.base_url || "";
      document.getElementById("setupLlmApiKey").value = "";
      fillSelect(document.getElementById("setupMarketProvider"), options.market_providers || {}, overview.config.market_data.provider || "demo");
      document.getElementById("setupMarketBaseUrl").value = overview.config.market_data.base_url || "";
      document.getElementById("setupMarketApiKey").value = "";
      fillSelect(document.getElementById("setupNewsProvider"), options.news_sources || {}, overview.config.news?.provider || "auto");
      fillSelect(document.getElementById("setupNewsLookback"), options.news_lookbacks || {}, overview.config.news?.lookback || "7d");
      renderSetupMarketHint();
    }

    function updateSetupModelOptions(reset = true) {
      const provider = document.getElementById("setupLlmProvider").value;
      const meta = (overview.options || {}).llm_models?.[provider] || {};
      const modelSelect = document.getElementById("setupLlmModel");
      modelSelect.innerHTML = "";
      const models = meta.models || [meta.default_model || ""];
      models.forEach(model => {
        const option = document.createElement("option");
        option.value = model;
        option.textContent = model;
        option.selected = model === (reset ? meta.default_model : overview.config.llm.model);
        modelSelect.appendChild(option);
      });
      if (provider === overview.config.llm.provider && !reset) {
        modelSelect.value = overview.config.llm.model;
      }
      document.getElementById("setupLlmBaseUrl").value = reset ? (meta.default_base_url || "") : (overview.config.llm.base_url || meta.default_base_url || "");
    }

    function renderSetupMarketHint() {
      const provider = document.getElementById("setupMarketProvider").value;
      const meta = (overview.options || {}).market_providers?.[provider] || {};
      const keyHint = meta.requires_api_key ? "需要 API key / token" : "不需要 API key";
      document.getElementById("setupMarketHint").innerHTML = `
        <div class="provider-note-row"><span>名称</span><strong>${escapeHtml(meta.label || provider)}</strong></div>
        <div class="provider-note-row"><span>认证</span><strong>${escapeHtml(keyHint)}</strong></div>
        <div class="provider-note-row"><span>状态</span><strong>${escapeHtml(meta.status || "-")}</strong></div>
        <p class="muted" style="line-height:1.55;margin-top:4px">${escapeHtml(meta.description || "")}</p>
      `;
    }

    async function completeSetup() {
      const status = document.getElementById("setupStatus");
      status.textContent = "正在保存配置...";
      const payload = {
        complete_onboarding: true,
        app: {
          language: document.getElementById("setupLanguage").value,
          cache_policy: document.getElementById("setupCachePolicy").value,
          timezone: document.getElementById("setupTimezone").value,
          onboarding_completed: true
        },
        llm: {
          provider: document.getElementById("setupLlmProvider").value,
          model: document.getElementById("setupLlmModel").value,
          base_url: document.getElementById("setupLlmBaseUrl").value,
          api_key: document.getElementById("setupLlmApiKey").value,
          keep_api_key: false
        },
        market_data: {
          provider: document.getElementById("setupMarketProvider").value,
          base_url: document.getElementById("setupMarketBaseUrl").value,
          api_key: document.getElementById("setupMarketApiKey").value,
          keep_api_key: false
        },
        news: {
          provider: document.getElementById("setupNewsProvider").value,
          lookback: document.getElementById("setupNewsLookback").value
        }
      };
      try {
        const result = await api("/api/config", { method: "POST", body: JSON.stringify(payload) });
        if (result.setup?.required) {
          status.textContent = "配置还不完整：远程模型或数据源需要填写对应 key / token。也可以选择 Local Template + Demo Local Data 先进入体验。";
          return;
        }
        status.textContent = "配置完成，正在进入 PortClaw...";
        await loadOverview();
      } catch (error) {
        status.textContent = "保存失败：" + error.message;
      }
    }

    function renderConfigForms() {
      const options = overview.options || {};
      fillSelect(document.getElementById("appLanguage"), options.languages || {}, overview.config.app?.language || "zh-CN");
      fillSelect(document.getElementById("cachePolicy"), options.cache_policies || {}, overview.config.app?.cache_policy || "standard");
      fillSelect(document.getElementById("appTimezone"), options.timezones || {}, overview.config.app?.timezone || "Asia/Shanghai");
      fillSelect(document.getElementById("llmProvider"), options.llm_models || {}, overview.config.llm.provider);
      updateModelOptions(false);
      document.getElementById("llmBaseUrl").value = overview.config.llm.base_url || "";
      document.getElementById("llmApiKey").value = "";
      document.getElementById("llmApiKey").dataset.clear = "false";

      fillSelect(document.getElementById("marketProvider"), options.market_providers || {}, overview.config.market_data.provider);
      document.getElementById("marketBaseUrl").value = overview.config.market_data.base_url || "";
      document.getElementById("marketApiKey").value = "";
      document.getElementById("marketApiKey").dataset.clear = "false";
      renderMarketProviderHint();
      fillSelect(document.getElementById("newsProvider"), options.news_sources || {}, overview.config.news?.provider || "auto");
      fillSelect(document.getElementById("newsLookback"), options.news_lookbacks || {}, overview.config.news?.lookback || "7d");
      renderNewsProviderHint();
    }

    function updateModelOptions(reset = true) {
      const provider = document.getElementById("llmProvider").value;
      const meta = (overview.options || {}).llm_models?.[provider] || {};
      const modelSelect = document.getElementById("llmModel");
      modelSelect.innerHTML = "";
      const models = meta.models || [meta.default_model || ""];
      models.forEach(model => {
        const option = document.createElement("option");
        option.value = model;
        option.textContent = model;
        option.selected = model === (reset ? meta.default_model : overview.config.llm.model);
        modelSelect.appendChild(option);
      });
      if (provider === overview.config.llm.provider && !reset) {
        modelSelect.value = overview.config.llm.model;
      }
      document.getElementById("llmBaseUrl").value = reset ? (meta.default_base_url || "") : (overview.config.llm.base_url || meta.default_base_url || "");
    }

    function renderMarketProviderHint() {
      const provider = document.getElementById("marketProvider").value;
      const meta = (overview.options || {}).market_providers?.[provider] || {};
      document.getElementById("marketProviderHint").innerHTML = `
        <div class="provider-note-row"><span>名称</span><strong>${escapeHtml(meta.label || provider)}</strong></div>
        <div class="provider-note-row"><span>类型</span><strong>${escapeHtml(meta.category || "-")}</strong></div>
        <div class="provider-note-row"><span>认证</span><strong>${escapeHtml(meta.auth_type || (meta.requires_api_key ? "API key" : "None"))}</strong></div>
        <div class="provider-note-row"><span>环境变量</span><strong>${escapeHtml((meta.env_vars || []).join(", ") || "None")}</strong></div>
        <div class="provider-note-row"><span>状态</span><strong>${escapeHtml(meta.status || "-")}</strong></div>
        <p class="muted" style="line-height:1.55;margin-top:4px">${escapeHtml(meta.description || "")}</p>
      `;
      if (!meta.requires_api_key) {
        document.getElementById("marketApiKey").placeholder = "该数据源不需要 API key，保存时会自动清空";
      } else {
        document.getElementById("marketApiKey").placeholder = "留空保留已有 key；输入新值会覆盖";
      }
    }

    function renderNewsProviderHint() {
      const provider = document.getElementById("newsProvider").value;
      const meta = (overview.options || {}).news_sources?.[provider] || {};
      document.getElementById("newsProviderHint").innerHTML = `
        <div class="provider-note-row"><span>模式</span><strong>${escapeHtml(meta.label || provider)}</strong></div>
        <p class="muted" style="line-height:1.55;margin-top:4px">${escapeHtml(meta.description || "")}</p>
      `;
    }

    function clearSecret(id) {
      const input = document.getElementById(id);
      input.value = "";
      input.dataset.clear = "true";
      input.placeholder = "保存后会清空当前 key";
    }

    function renderProviders(providers, active) {
      const target = document.getElementById("providers");
      target.innerHTML = "";
      Object.entries(providers).forEach(([key, item]) => {
        const implemented = item.status === "implemented";
        const connected = key === active && implemented;
        const stateLabel = connected ? "Connected" : implemented ? "Optional" : "Planned";
        const stateClass = connected ? "connected" : implemented ? "optional" : "planned";
        const dotClass = connected ? "connected" : "muted";
        const row = document.createElement("div");
        row.className = `provider ${stateClass}`;
        row.innerHTML = `
          <span class="status-dot ${dotClass}"></span>
          <div><strong>${escapeHtml(key)} · ${escapeHtml(item.label || key)}</strong><small>${escapeHtml(item.category || "")} · ${escapeHtml(item.description || "")}</small></div>
          <div class="provider-status"><span>${stateLabel}</span><span class="pill ${connected ? "ok" : implemented ? "" : "warn"}">${escapeHtml(item.status || "unknown")}</span></div>
        `;
        target.appendChild(row);
      });
    }

    function renderPortfolio(portfolio) {
      document.getElementById("userId").value = portfolio.user_id || "local_user";
      document.getElementById("baseCurrency").value = portfolio.base_currency || "USD";
      document.getElementById("cash").value = portfolio.cash || 0;
      const body = document.getElementById("positions");
      body.innerHTML = "";
      (portfolio.positions || []).forEach(addRow);
    }

    function addRow(item = {}) {
      const body = document.getElementById("positions");
      const tr = document.createElement("tr");
      [
        ["symbol", "text", item.symbol || ""],
        ["name", "text", item.name || ""],
        ["sector", "text", item.sector || ""],
        ["quantity", "number", item.quantity || 0],
        ["total_cost", "number", (Number(item.average_cost || 0) * Number(item.quantity || 0)) || 0]
      ].forEach(([field, type, value]) => {
        const td = document.createElement("td");
        const input = document.createElement("input");
        input.dataset.field = field;
        input.type = type;
        input.value = value;
        if (type === "number") input.step = "0.0001";
        td.appendChild(input);
        tr.appendChild(td);
      });
      const action = document.createElement("td");
      const remove = document.createElement("button");
      remove.textContent = "删除";
      remove.onclick = () => tr.remove();
      action.appendChild(remove);
      tr.appendChild(action);
      body.appendChild(tr);
    }

    function collectPortfolio() {
      const positions = [...document.querySelectorAll("#positions tr")].map(row => {
        const item = {};
        row.querySelectorAll("input").forEach(input => item[input.dataset.field] = input.value);
        const quantity = Number(item.quantity || 0);
        const totalCost = Number(item.total_cost || 0);
        item.average_cost = quantity ? totalCost / quantity : 0;
        delete item.total_cost;
        return item;
      }).filter(item => item.symbol);
      return {
        user_id: document.getElementById("userId").value,
        base_currency: document.getElementById("baseCurrency").value,
        cash: document.getElementById("cash").value,
        positions
      };
    }

    async function savePortfolio() {
      const toast = document.getElementById("portfolioToast");
      toast.textContent = "保存中...";
      try {
        const result = await api("/api/portfolio", { method: "POST", body: JSON.stringify(collectPortfolio()) });
        overview.portfolio = result.portfolio;
        dashboard = await api("/api/dashboard");
        renderOverview();
        renderDashboard();
        toast.textContent = "已保存到 " + result.path;
      } catch (error) {
        toast.textContent = error.message;
      }
    }

    async function saveRuntimeConfig() {
      const toast = document.getElementById("configToast");
      const output = document.getElementById("configOutput");
      toast.textContent = "保存中...";
      const llmKey = document.getElementById("llmApiKey").value;
      const marketKey = document.getElementById("marketApiKey").value;
      const clearLlmKey = document.getElementById("llmApiKey").dataset.clear === "true";
      const clearMarketKey = document.getElementById("marketApiKey").dataset.clear === "true";
      const payload = {
        llm: {
          provider: document.getElementById("llmProvider").value,
          model: document.getElementById("llmModel").value,
          base_url: document.getElementById("llmBaseUrl").value,
          api_key: llmKey,
          keep_api_key: !clearLlmKey && !llmKey
        },
        market_data: {
          provider: document.getElementById("marketProvider").value,
          base_url: document.getElementById("marketBaseUrl").value,
          api_key: marketKey,
          keep_api_key: !clearMarketKey && !marketKey
        },
        news: {
          provider: document.getElementById("newsProvider").value,
          lookback: document.getElementById("newsLookback").value
        },
        app: {
          language: document.getElementById("appLanguage").value,
          cache_policy: document.getElementById("cachePolicy").value,
          timezone: document.getElementById("appTimezone").value,
          onboarding_completed: true
        }
      };
      try {
        const result = await api("/api/config", { method: "POST", body: JSON.stringify(payload) });
        overview.config = result.config;
        overview.setup = result.setup || overview.setup;
        document.documentElement.lang = overview.config.app?.language || "zh-CN";
        renderOverview();
        renderConfigForms();
        toast.textContent = "已保存到 " + result.path;
        output.innerHTML = `<div class="status-card">配置已保存。<small>你可以点击“验证状态”查看当前模型和数据源 ready 状态。</small></div>`;
      } catch (error) {
        toast.textContent = error.message;
      }
    }

    async function clearRuntimeCache() {
      const output = document.getElementById("configOutput");
      output.innerHTML = `<div class="status-card">正在清理缓存。<small>不会删除 API key、持仓或交易日志。</small></div>`;
      try {
        const result = await api("/api/cache/clear", { method: "POST", body: JSON.stringify({}) });
        output.innerHTML = `<div class="status-card">缓存已清理。<small>清理项目 ${result.count || 0} 个。</small></div>`;
      } catch (error) {
        output.innerHTML = `<div class="status-card">缓存清理失败<small>${escapeHtml(error.message)}</small></div>`;
      }
    }

    function commandLabel(action) {
      return {
        daily: "今日风险日报",
        portfolio: "当前持仓解释",
        status: "运行状态",
        "config-show": "本地配置摘要",
        "data-sources": "数据源能力",
        models: "模型能力"
      }[action] || action;
    }

    function commandText(result) {
      return [result.stdout, result.stderr].filter(Boolean).join("\n").trim() || "没有返回内容。";
    }

    function setChatLoading(target, label) {
      target.innerHTML = `<div class="message system"><div class="bubble">${escapeHtml(label)}</div></div>`;
    }

    function appendMessage(target, role, meta, text) {
      target.querySelector(".chat-empty")?.remove();
      const message = document.createElement("div");
      message.className = "message " + role;
      message.innerHTML = `<div class="message-meta">${escapeHtml(meta)}</div><div class="bubble">${escapeHtml(text)}</div>`;
      target.appendChild(message);
      target.scrollTop = target.scrollHeight;
      return message;
    }

    function renderStatusResult(target, title, result) {
      const text = commandText(result);
      const lines = text.split("\n").map(line => line.trim()).filter(Boolean);
      const cards = lines.slice(0, 18).map(line => {
        const parts = line.split(/:|=/);
        if (parts.length >= 2 && parts[0].length < 32) {
          return `<div class="status-card"><strong>${escapeHtml(parts[0].trim())}</strong><small>${escapeHtml(parts.slice(1).join(":").trim())}</small></div>`;
        }
        return `<div class="status-card">${escapeHtml(line)}</div>`;
      }).join("");
      target.innerHTML = `<div class="status-card"><strong>${escapeHtml(title)}</strong><small>${result.ok ? "完成" : "需要检查"}</small></div>${cards}`;
    }

    function renderCommandResult(target, action, result) {
      const title = commandLabel(action);
      if (target.classList.contains("chat-output")) {
        target.innerHTML = "";
        appendMessage(target, "agent", title, commandText(result));
        return;
      }
      if (target.classList.contains("status-output")) {
        renderStatusResult(target, title, result);
        return;
      }
      target.textContent = commandText(result);
    }

    async function runAction(action) {
      setBusy("running " + action);
      const output = commandOutputTarget();
      if (output.classList.contains("chat-output")) {
        setChatLoading(output, "PortClaw 正在整理 " + commandLabel(action) + "...");
      } else if (output.classList.contains("status-output")) {
        output.innerHTML = `<div class="status-card">正在验证，请稍候。<small>${escapeHtml(commandLabel(action))}</small></div>`;
      } else {
        output.textContent = "运行中...";
      }
      try {
        const result = await api("/api/run", { method: "POST", body: JSON.stringify({ action }) });
        renderCommandResult(output, action, result);
        clearBusy(result.ok ? "done" : "failed");
      } catch (error) {
        if (output.classList.contains("chat-output")) {
          output.innerHTML = "";
          appendMessage(output, "agent", "执行失败", error.message);
        } else if (output.classList.contains("status-output")) {
          output.innerHTML = `<div class="status-card">执行失败<small>${escapeHtml(error.message)}</small></div>`;
        } else {
          output.textContent = error.message;
        }
        clearBusy("failed");
      }
    }

    async function askQuestion() {
      const input = document.getElementById("question");
      const question = input.value.trim();
      if (!question) return;
      setBusy("asking");
      const output = document.getElementById("askOutput");
      appendMessage(output, "user", "Operator Query", question);
      input.value = "";
      const loading = appendMessage(output, "system", "Risk Intelligence Layer", "正在解析组合、风险画像、交易日志与可用市场数据...");
      try {
        const result = await api("/api/ask", { method: "POST", body: JSON.stringify({ question }) });
        loading.remove();
        appendMessage(output, "agent", result.ok ? "Risk Intelligence Layer" : "Risk Intelligence Layer · Review Required", commandText(result));
        clearBusy(result.ok ? "done" : "failed");
      } catch (error) {
        loading.remove();
        appendMessage(output, "agent", "Request Failed", error.message);
        clearBusy("failed");
      }
    }

    function askPreset(text) {
      const input = document.getElementById("question");
      input.value = text;
      askQuestion();
    }

    function handleQuestionKey(event) {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        askQuestion();
      }
    }

    initAmbientBackground();
    loadOverview().catch(error => {
      document.getElementById("riskSummaryPanel").textContent = "启动失败：" + error.message;
    });
  </script>
</body>
</html>
"""


def main(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    server = ThreadingHTTPServer((host, port), PortClawAppHandler)
    url = f"http://{host}:{port}"
    print(f"PortClaw App running at {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nPortClaw App stopped.")
    finally:
        server.server_close()
