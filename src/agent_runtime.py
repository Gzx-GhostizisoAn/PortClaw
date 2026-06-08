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
        held_symbols = {position.asset.symbol for position in snapshot.positions}
        watchlist_symbols = [item.symbol for item in asset_metrics if item.symbol not in held_symbols]

        lines = [
            "Portfolio input file",
            f"- path: {portfolio_path}",
            f"- user_id: {snapshot.user_id}",
            f"- base_currency: {snapshot.base_currency}",
            f"- cash: {snapshot.cash:.2f}",
            f"- total_market_value: {snapshot.total_market_value:.2f}",
            f"- market_data_provider: {snapshot.metadata.get('market_data_provider', self.config.market_data.provider)}",
            "",
            "Positions are the assets the user currently holds:",
        ]
        for position in snapshot.positions:
            market_note = position.asset.metadata.get("market_data_error") or "ok"
            lines.append(
                f"- {position.asset.symbol}: quantity={position.quantity}, "
                f"average_cost={position.average_cost}, market_price={position.market_price}, "
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
                "- market_price is overwritten by configured market data when the adapter succeeds.",
                "- if market data fails, the agent falls back to the local market_price.",
                "- watchlist entries are not holdings; they are only scanned for strategy candidates.",
            ]
        )
        return "\n".join(lines)

    def _build_daily_brief(self, portfolio_path: Path | None = None):
        snapshot, asset_metrics = load_portfolio_snapshot(self.config, portfolio_path)
        news_items, news_events, news_impacts, news_summary = self.news_layer.build(snapshot)
        return self.pipeline.run(
            snapshot=snapshot,
            asset_metrics=asset_metrics,
            news_items=news_items,
            news_events=news_events,
            news_impacts=news_impacts,
            news_summary=news_summary,
        )

    def handle_message(self, message: str) -> AgentResponse:
        normalized = message.strip().lower()
        if not normalized:
            return AgentResponse(text="Please enter a message.")
        if normalized in {"help", "?", "h"}:
            return AgentResponse(text=self.help_text())
        if normalized in {"status", "config", "settings"} or "status" in normalized:
            return AgentResponse(text=self.status())
        if normalized in {"daily", "brief", "report", "run"}:
            return self.run_daily()
        if normalized in {"portfolio", "holdings", "positions"}:
            return AgentResponse(text=self.explain_portfolio_input())
        return self.answer(message)

    def help_text(self) -> str:
        return (
            "Local finance agent chat\n"
            "- Ask freely, for example: Why is my portfolio risky today?\n"
            "- daily: generate the full daily brief\n"
            "- portfolio: explain the local holdings input file\n"
            "- status: show runtime and API-key readiness\n"
            "- help: show this message"
        )
