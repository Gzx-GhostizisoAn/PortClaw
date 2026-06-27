from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .audit import AuditStore
from .config import AgentConfig, PROJECT_ROOT, available_market_data_providers, load_config
from .data.news import NewsLayer
from .pipeline import DailyPipeline
from .reporting import ReportGenerator
from .ledger import load_portfolio_snapshot
from .portfolio_input import default_portfolio_path
from .schemas import DataSourceStatus


@dataclass
class AgentResponse:
    text: str
    audit_id: Optional[str] = None
    handled_by: str = "local_agent"


class LocalFinanceAgent:
    def __init__(self, config: AgentConfig | None = None):
        self.config = config or load_config()
        self.pipeline = DailyPipeline()
        self.news_layer = NewsLayer(self.config)
        self.reporter = ReportGenerator(self.config)
        self.audit_store = AuditStore(PROJECT_ROOT / self.config.storage.audit_dir)

    def status(self) -> str:
        llm_ready = self.config.llm.provider == "local_template" or bool(self.config.llm.api_key)
        market_meta = available_market_data_providers().get(self.config.market_data.provider, {})
        market_ready = not market_meta.get("requires_api_key", True) or bool(self.config.market_data.api_key)
        enabled_channels = [item.channel_id for item in self.config.channels if item.enabled]
        return (
            "Local finance agent status\n"
            f"- user_id: {self.config.user_id}\n"
            f"- llm_provider: {self.config.llm.provider}\n"
            f"- llm_model: {self.config.llm.model}\n"
            f"- llm_base_url: {self.config.llm.base_url or 'default'}\n"
            f"- llm_ready: {llm_ready}\n"
            f"- market_data_provider: {self.config.market_data.provider}\n"
            f"- market_data_mode: {self.config.market_data.mode}\n"
            f"- market_data_ready: {market_ready}\n"
            f"- enabled_channels: {', '.join(enabled_channels) or 'none'}\n"
            f"- audit_dir: {self.config.storage.audit_dir}\n"
            f"- message_dir: {self.config.storage.message_dir}"
        )

    def run_daily(self, portfolio_path: Path | None = None) -> AgentResponse:
        brief = self._build_daily_brief(portfolio_path)
        llm_input, report = self.reporter.generate_report(brief)
        audit = self.audit_store.save_daily_run(brief=brief, llm_input=llm_input, llm_output=report)
        return AgentResponse(text=report, audit_id=audit.audit_id)

    def answer(self, question: str, portfolio_path: Path | None = None) -> AgentResponse:
        brief = self._build_daily_brief(portfolio_path)
        llm_input, answer = self.reporter.answer_question(brief, question)
        audit = self.audit_store.save_daily_run(brief=brief, llm_input=llm_input, llm_output=answer)
        return AgentResponse(text=answer, audit_id=audit.audit_id)

    def explain_portfolio_input(self, portfolio_path: Path | None = None) -> str:
        portfolio_path = portfolio_path or default_portfolio_path()
        snapshot, asset_metrics = load_portfolio_snapshot(self.config, portfolio_path)
        source_status = [
            item
            for item in build_data_source_status(self.config, snapshot, asset_metrics, self.news_layer.fetcher.last_status)
            if item.component == "market_data"
        ]
        held_symbols = {position.asset.symbol for position in snapshot.positions}
        watchlist_symbols = [item.symbol for item in asset_metrics if item.symbol not in held_symbols]

        lines = [
            "Data source status",
            *format_data_source_status(source_status),
            "",
            "Portfolio input file",
            f"- path: {portfolio_path}",
            f"- user_id: {snapshot.user_id}",
            f"- base_currency: {snapshot.base_currency}",
            f"- cash: {snapshot.cash:.2f}",
            f"- total_market_value: {snapshot.total_market_value:.2f}",
            f"- market_data_provider: {snapshot.metadata.get('market_data_provider', self.config.market_data.provider)}",
            f"- daily_return: {_format_pct(calculate_daily_return(snapshot))}",
            f"- trade_ledger: {_format_trade_ledger(snapshot.metadata.get('trade_ledger', {}))}",
            "",
            "Positions are the assets the user currently holds:",
        ]
        for position in snapshot.positions:
            market_note = position.asset.metadata.get("market_data_error") or "ok"
            lines.append(
                f"- {position.asset.symbol}: quantity={position.quantity}, "
                f"average_cost={position.average_cost}, previous_close={_format_number(position.previous_close)}, "
                f"market_price={position.market_price}, daily_pnl={_format_number(position.daily_pnl)}, "
                f"daily_pnl_pct={_format_pct(position.daily_pnl_pct)}, "
                f"weight={(position.weight or 0):.2%}, market_data={market_note}"
            )
        lines.extend(
            [
                "",
                f"Watchlist assets scanned for strategy signals: {', '.join(watchlist_symbols) or 'none'}",
                "",
                "How to edit holdings:",
                f"- Edit {portfolio_path} or run `python agent.py holdings`.",
                "- quantity is how many shares/units are held.",
                "- average_cost is the user's private cost basis.",
                "- market_price is a derived runtime field from configured market data, not a user-maintained holding input.",
                "- users do not maintain live market_price in holdings; if market data fails, return metrics are unavailable and structure displays use cost basis as a fallback.",
                "- import trade rows with `python agent.py import-trades --csv data/trade_template.csv` to update quantity, cash, cost basis, and behavior logs.",
                "- watchlist entries are not holdings; they are only scanned for strategy candidates.",
            ]
        )
        return "\n".join(lines)

    def _build_daily_brief(self, portfolio_path: Path | None = None):
        snapshot, asset_metrics = load_portfolio_snapshot(self.config, portfolio_path)
        news_items, news_events, news_impacts, news_summary = self.news_layer.build(snapshot)
        brief = self.pipeline.run(
            snapshot=snapshot,
            asset_metrics=asset_metrics,
            news_items=news_items,
            news_events=news_events,
            news_impacts=news_impacts,
            news_summary=news_summary,
        )
        brief.data_source_status = build_data_source_status(
            config=self.config,
            snapshot=snapshot,
            asset_metrics=asset_metrics,
            news_status=self.news_layer.fetcher.last_status,
        )
        return brief

    def handle_message(self, message: str) -> AgentResponse:
        normalized = message.strip().lower()
        if not normalized:
            return AgentResponse(text="Please enter a message.")
        command = normalized[1:] if normalized.startswith("/") else normalized
        if command in {"help", "?", "h"}:
            return AgentResponse(text=self.help_text())
        if command in {"status", "config", "settings"}:
            return AgentResponse(text=self.status())
        if command in {"daily", "brief", "report", "run"}:
            return self.run_daily()
        if command in {"portfolio", "holdings", "positions"}:
            return AgentResponse(text=self.explain_portfolio_input())
        return self.answer(message)

    def help_text(self) -> str:
        return (
            "Local finance agent chat\n"
            "- Ask freely, for example: Why is my portfolio risky today?\n"
            "- /daily or daily: generate the full daily brief\n"
            "- /portfolio or portfolio: explain the local holdings input file\n"
            "- /status or status: show runtime and API-key readiness\n"
            "- /help or help: show this message\n"
            "- Any other message is treated as a model-backed question when an LLM provider is configured."
        )


def calculate_daily_return(snapshot) -> float | None:
    daily_pnl = 0.0
    previous_total = snapshot.cash
    has_daily_data = False
    for position in snapshot.positions:
        if position.daily_pnl is None or position.previous_close is None:
            continue
        daily_pnl += position.daily_pnl
        previous_total += position.quantity * position.previous_close
        has_daily_data = True
    if not has_daily_data or previous_total <= 0:
        return None
    return daily_pnl / previous_total


def _format_number(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.2f}"


def _format_pct(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.2%}"


def _format_trade_ledger(trade_ledger: dict[str, object]) -> str:
    if not trade_ledger:
        return "not synced from trade rows"
    return (
        f"last_synced_at={trade_ledger.get('last_synced_at', 'unknown')}, "
        f"last_import_count={trade_ledger.get('last_import_count', 0)}, "
        f"cumulative_realized_pnl={float(trade_ledger.get('cumulative_realized_pnl', 0.0)):.2f}, "
        f"log={trade_ledger.get('trade_log', 'unknown')}"
    )


def build_data_source_status(
    config: AgentConfig,
    snapshot,
    asset_metrics,
    news_status: dict[str, object] | None = None,
) -> list[DataSourceStatus]:
    statuses = [
        _market_data_status(config, snapshot, asset_metrics),
        _news_data_status(config, news_status or {}),
    ]
    snapshot.metadata["data_source_status"] = [item.model_dump(mode="json") for item in statuses]
    return statuses


def _market_data_status(config: AgentConfig, snapshot, asset_metrics) -> DataSourceStatus:
    provider = config.market_data.provider
    provider_symbols: list[str] = []
    fallback_symbols: list[str] = []
    errors: list[str] = []
    fallback_fields = set()
    used_fields = {"positions.quantity", "positions.average_cost", "cash"}

    for position in snapshot.positions:
        metadata = position.asset.metadata
        field_sources = metadata.get("field_sources", {})
        error = metadata.get("market_data_error")
        if error:
            fallback_symbols.append(position.asset.symbol)
            errors.append(f"{position.asset.symbol}: {error}")
        else:
            provider_symbols.append(position.asset.symbol)
        for field_name, source in field_sources.items():
            if source == "provider_history":
                used_fields.add(f"positions.{field_name}")
            elif source in {"portfolio_file_fallback", "cost_basis_fallback"}:
                fallback_fields.add(f"positions.{field_name}")

    for metric in asset_metrics:
        source = metric.metadata.get("metric_source")
        if source == "market_history":
            used_fields.add("asset_metrics")
        elif source:
            fallback_fields.add("asset_metrics")
            error = metric.metadata.get("market_data_error")
            if error and f"{metric.symbol}: {error}" not in errors:
                errors.append(f"{metric.symbol}: {error}")

    if provider_symbols and fallback_symbols:
        status = "partial"
        note = "Some symbols used provider history; others used cost basis fallback for structure displays."
    elif provider_symbols:
        status = "ok"
        note = "Market price, previous close, daily P&L, and history-based metrics used provider history where available."
    else:
        status = "fallback"
        fallback_fields.update({"positions.market_price", "portfolio.total_market_value", "portfolio.total_return", "asset_metrics"})
        note = "No requested symbols returned usable provider history; return metrics are unavailable and cost basis is used only for structure displays."

    if not snapshot.positions:
        status = "empty"
        note = "No positions were available for market-data enrichment."

    return DataSourceStatus(
        component="market_data",
        provider=provider,
        status=status,
        used_fields=sorted(used_fields),
        fallback_fields=sorted(fallback_fields),
        affected_symbols=sorted(set(fallback_symbols)),
        errors=_unique(errors),
        note=note,
    )


def _news_data_status(config: AgentConfig, news_status: dict[str, object]) -> DataSourceStatus:
    provider = str(news_status.get("provider") or config.market_data.provider)
    status = str(news_status.get("status") or "unknown")
    errors = [str(item) for item in news_status.get("errors", [])]
    item_count = int(news_status.get("item_count") or 0)
    if status == "ok":
        note = f"{item_count} news item(s) collected from provider and used for event impact analysis."
        used_fields = ["news_items", "news_events", "news_impacts"]
        fallback_fields: list[str] = []
    elif status == "empty":
        note = "Provider returned no news items; news risk was not available for this run."
        used_fields = []
        fallback_fields = ["news_items", "news_events", "news_impacts"]
    elif status == "not_implemented":
        note = "Configured provider does not yet have a news adapter; news risk is unavailable."
        used_fields = []
        fallback_fields = ["news_items", "news_events", "news_impacts"]
    elif status == "partial":
        note = f"{item_count} news item(s) collected, but one or more symbol fetches failed."
        used_fields = ["news_items", "news_events", "news_impacts"]
        fallback_fields = []
    else:
        note = "News provider failed or is unavailable; news risk was not available for this run."
        used_fields = []
        fallback_fields = ["news_items", "news_events", "news_impacts"]

    return DataSourceStatus(
        component="news",
        provider=provider,
        status=status,
        used_fields=used_fields,
        fallback_fields=fallback_fields,
        errors=_unique(errors),
        note=note,
    )


def _unique(items: list[str]) -> list[str]:
    output: list[str] = []
    for item in items:
        if item and item not in output:
            output.append(item)
    return output


def format_data_source_status(statuses: list[DataSourceStatus]) -> list[str]:
    lines: list[str] = []
    for item in statuses:
        symbol_text = f"; affected_symbols={', '.join(item.affected_symbols)}" if item.affected_symbols else ""
        lines.append(f"- {item.component}: provider={item.provider}, status={item.status}{symbol_text}")
        if item.used_fields:
            lines.append(f"  used_fields: {', '.join(item.used_fields)}")
        if item.fallback_fields:
            lines.append(f"  fallback_fields: {', '.join(item.fallback_fields)}")
        if item.note:
            lines.append(f"  note: {item.note}")
        for error in item.errors[:5]:
            lines.append(f"  error: {error}")
        if len(item.errors) > 5:
            lines.append(f"  error: ... {len(item.errors) - 5} more")
    return lines
