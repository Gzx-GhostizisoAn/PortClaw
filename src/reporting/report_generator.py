from __future__ import annotations

import json
import re
from typing import Any, Dict

from ..config import AgentConfig
from ..schemas import DailyBrief


REPORT_STYLE_INSTRUCTIONS = (
    "Write in clear Chinese plain text. Do not use Markdown syntax such as ##, **, "
    "horizontal rules, tables, block quotes, or code fences. Use short numbered sections "
    "with plain labels. Explain in a systematic hierarchy: conclusion, key reasons, "
    "risk themes, evidence, and next review points. Keep paragraphs concise and readable."
)


class ReportGenerator:
    def __init__(self, config: AgentConfig):
        self.config = config

    def build_llm_input(self, brief: DailyBrief) -> Dict[str, Any]:
        return {
            "as_of": brief.as_of.isoformat(),
            "data_source_status": [item.model_dump(mode="json") for item in brief.data_source_status],
            "portfolio_summary": {
                "total_market_value": brief.portfolio_snapshot.total_market_value,
                "total_cost": brief.portfolio_snapshot.total_cost,
                "cash": brief.portfolio_snapshot.cash,
                "total_return": brief.portfolio_metrics.total_return,
                "daily_return": brief.portfolio_metrics.daily_return,
                "largest_position_weight": brief.portfolio_metrics.largest_position_weight,
                "positions": [
                    {
                        "symbol": position.asset.symbol,
                        "quantity": position.quantity,
                        "market_price": position.market_price,
                        "previous_close": position.previous_close,
                        "market_value": position.market_value,
                        "daily_pnl": position.daily_pnl,
                        "daily_pnl_pct": position.daily_pnl_pct,
                        "weight": position.weight,
                    }
                    for position in brief.portfolio_snapshot.positions
                ],
            },
            "risk_themes": [item.model_dump(mode="json") for item in brief.risk_themes],
            "news_layer": {
                "items": [item.model_dump(mode="json") for item in brief.news_items],
                "events": [item.model_dump(mode="json") for item in brief.news_events],
                "impacts": [item.model_dump(mode="json") for item in brief.news_impacts],
            },
            "signals": [item.model_dump(mode="json") for item in brief.signals],
            "strategy_candidates": [item.model_dump(mode="json") for item in brief.strategy_candidates],
            "news_summary": brief.news_summary,
            "human_review_items": brief.human_review_items,
            "disclaimer": brief.disclaimer,
        }

    def generate_report(self, brief: DailyBrief) -> tuple[Dict[str, Any], str]:
        llm_input = self.build_llm_input(brief)
        if self.config.llm.provider != "local_template" and self.config.llm.api_key:
            remote = self._try_remote_report(llm_input)
            if remote:
                return llm_input, self._with_source_notice(brief, remote)
        elif self.config.llm.provider != "local_template":
            return llm_input, self._with_source_notice(
                brief,
                self._local_fallback_with_reason(
                    "Remote LLM is configured but no API key is available.",
                    self._local_template_report(brief),
                ),
            )
        return llm_input, self._with_source_notice(brief, self._local_template_report(brief))

    def answer_question(self, brief: DailyBrief, question: str) -> tuple[Dict[str, Any], str]:
        llm_input = self.build_llm_input(brief)
        llm_input["user_question"] = question
        if self.config.llm.provider != "local_template" and self.config.llm.api_key:
            remote = self._try_remote_answer(llm_input, question)
            if remote:
                return llm_input, self._with_source_notice(brief, remote)
        elif self.config.llm.provider != "local_template":
            return llm_input, self._with_source_notice(
                brief,
                self._local_fallback_with_reason(
                    "Remote LLM is configured but no API key is available.",
                    self._local_template_answer(brief, question),
                ),
            )
        return llm_input, self._with_source_notice(brief, self._local_template_answer(brief, question))

    def _try_remote_report(self, llm_input: Dict[str, Any]) -> str | None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            return self._local_fallback_with_reason(
                f"Remote LLM client is not installed: {exc}",
                self._local_template_from_input(llm_input),
            )

        try:
            client = OpenAI(
                api_key=self.config.llm.api_key,
                base_url=self.config.llm.base_url or None,
            )
            response = client.chat.completions.create(
                model=self.config.llm.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a cautious local financial research agent. "
                            "Only explain the structured JSON provided by the analytics system. "
                            "Treat ranked risk_themes as the primary risk conclusion and signals as supporting evidence. "
                            "Do not invent prices, holdings, facts, or advice beyond the input. "
                            f"{REPORT_STYLE_INSTRUCTIONS}"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(llm_input, ensure_ascii=False, indent=2),
                    },
                ],
                temperature=0.2,
            )
            return self._clean_model_text(response.choices[0].message.content or "")
        except Exception as exc:
            return self._local_fallback_with_reason(
                f"Remote LLM report failed: {exc}",
                self._local_template_from_input(llm_input),
            )

    def _try_remote_answer(self, llm_input: Dict[str, Any], question: str) -> str | None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            return self._local_fallback_with_reason(
                f"Remote LLM client is not installed: {exc}",
                self._local_template_answer_from_input(llm_input),
            )

        try:
            client = OpenAI(
                api_key=self.config.llm.api_key,
                base_url=self.config.llm.base_url or None,
            )
            response = client.chat.completions.create(
                model=self.config.llm.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a local financial research agent. Answer only from the structured "
                            "DailyBrief JSON. Do not invent holdings, prices, market data, or investment advice. "
                            "Prioritize ranked risk_themes, then use mapped signals as evidence. "
                            "If the data is insufficient, say what is missing. Write in Chinese when the user writes Chinese. "
                            f"{REPORT_STYLE_INSTRUCTIONS}"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Question: {question}\n\n"
                            f"Structured DailyBrief JSON:\n{json.dumps(llm_input, ensure_ascii=False, indent=2)}"
                        ),
                    },
                ],
                temperature=0.2,
            )
            return self._clean_model_text(response.choices[0].message.content or "")
        except Exception as exc:
            return self._local_fallback_with_reason(
                f"Remote LLM answer failed: {exc}",
                self._local_template_answer_from_input(llm_input),
            )

    def _local_template_report(self, brief: DailyBrief) -> str:
        total_return = brief.portfolio_metrics.total_return
        total_return_text = "unknown" if total_return is None else f"{total_return:.2%}"
        daily_return = brief.portfolio_metrics.daily_return
        daily_return_text = "unknown - latest and previous close are required" if daily_return is None else f"{daily_return:.2%}"
        daily_pnl = sum(position.daily_pnl or 0.0 for position in brief.portfolio_snapshot.positions)
        themes = self._format_risk_themes(brief.risk_themes) or "暂无主要风险主题。"
        signals = self._format_signals(brief.signals) or "暂无触发信号。"
        candidates = self._format_candidates(brief.strategy_candidates) or "暂无策略候选。"
        news = self._format_news_impacts(brief.news_impacts) or "暂无组合相关的新闻影响。"

        return (
            "本地每日组合分析\n\n"
            "1. 组合概览\n"
            f"总市值：{brief.portfolio_snapshot.total_market_value:.2f} {brief.portfolio_snapshot.base_currency}\n"
            f"总收益率：{total_return_text}\n"
            f"今日收益率：{daily_return_text}\n"
            f"今日估算盈亏：{daily_pnl:.2f} {brief.portfolio_snapshot.base_currency}\n"
            f"最大单一持仓权重：{(brief.portfolio_metrics.largest_position_weight or 0):.2%}\n\n"
            "2. 优先风险主题\n"
            f"{themes}\n\n"
            "3. 触发信号\n"
            f"{signals}\n\n"
            "4. 策略候选\n"
            f"{candidates}\n\n"
            "5. 新闻影响层\n"
            f"{news}\n\n"
            f"风险提示：{brief.disclaimer}"
        )

    def _local_template_answer(self, brief: DailyBrief, question: str) -> str:
        total_return = brief.portfolio_metrics.total_return
        total_return_text = "unknown" if total_return is None else f"{total_return:.2%}"
        daily_return = brief.portfolio_metrics.daily_return
        daily_return_text = "unknown - latest and previous close are required" if daily_return is None else f"{daily_return:.2%}"
        signal_text = "\n".join(
            f"{index}. 严重度 {item.severity.value}，对象 {item.target}：{item.summary}"
            for index, item in enumerate(brief.signals[:5], start=1)
        ) or "暂无触发信号。"
        theme_text = "\n".join(
            f"{index}. 排名 {item.rank or index}，严重度 {item.severity.value}，{item.title}。"
            f"优先级 {item.priority_score:.1f}/100。{item.summary}"
            for index, item in enumerate(brief.risk_themes[:5], start=1)
        ) or "暂无主要风险主题。"
        candidate_text = "\n".join(
            f"{index}. {item.target}：{item.summary}"
            for index, item in enumerate(brief.strategy_candidates[:5], start=1)
        ) or "暂无策略候选。"
        return (
            f"问题：{question}\n\n"
            "1. 简要结论\n"
            "以下回答来自当前本地 DailyBrief 结构化分析，不直接解释原始行情或交易数据。\n\n"
            "2. 组合状态\n"
            f"组合市值：{brief.portfolio_snapshot.total_market_value:.2f} {brief.portfolio_snapshot.base_currency}\n"
            f"总收益率：{total_return_text}\n"
            f"今日收益率：{daily_return_text}\n"
            f"最大单一持仓权重：{(brief.portfolio_metrics.largest_position_weight or 0):.2%}\n\n"
            "3. 优先风险主题\n"
            f"{theme_text}\n\n"
            "4. 证据信号\n"
            f"{signal_text}\n\n"
            "5. 策略候选\n"
            f"{candidate_text}"
        )

    def _format_risk_themes(self, themes: list[Any]) -> str:
        return "\n".join(
            f"{index}. 排名 {item.rank or index}，严重度 {item.severity.value}，{item.title}。"
            f"优先级 {item.priority_score:.1f}/100。{item.summary}"
            for index, item in enumerate(themes, start=1)
        )

    def _format_signals(self, signals: list[Any]) -> str:
        return "\n".join(
            f"{index}. 严重度 {item.severity.value}，对象 {item.target}：{item.summary}"
            for index, item in enumerate(signals, start=1)
        )

    def _format_candidates(self, candidates: list[Any]) -> str:
        return "\n".join(f"{index}. {item.target}：{item.summary}" for index, item in enumerate(candidates, start=1))

    def _format_news_impacts(self, impacts: list[Any]) -> str:
        sorted_impacts = sorted(impacts, key=lambda impact: impact.news_impact, reverse=True)[:5]
        return "\n".join(
            f"{index}. 主题 {item.theme_key}，新闻影响 {item.news_impact:.1f}/100，"
            f"基础影响 {item.base_impact:.1f}/100，放大系数 {item.amplification_factor:.2f}x，"
            f"组合暴露 {item.portfolio_exposure:.1%}，相关标的 {', '.join(item.affected_symbols) or 'none'}。"
            for index, item in enumerate(sorted_impacts, start=1)
        )

    def _with_source_notice(self, brief: DailyBrief, body: str) -> str:
        if not brief.data_source_status:
            return body
        return f"{self._format_data_source_status(brief.data_source_status)}\n\n{body}"

    def _format_data_source_status(self, statuses: list[Any]) -> str:
        lines = ["数据源状态"]
        for index, item in enumerate(statuses, start=1):
            affected = f"，受影响标的：{', '.join(item.affected_symbols)}" if item.affected_symbols else ""
            lines.append(f"{index}. {item.component}：provider={item.provider}，status={item.status}{affected}")
            if item.used_fields:
                lines.append(f"   真实数据字段：{', '.join(item.used_fields)}")
            if item.fallback_fields:
                lines.append(f"   本地回退字段：{', '.join(item.fallback_fields)}")
            if item.note:
                lines.append(f"   说明：{item.note}")
            for error in item.errors[:5]:
                lines.append(f"   错误：{error}")
            if len(item.errors) > 5:
                lines.append(f"   错误：另有 {len(item.errors) - 5} 条未显示")
        return "\n".join(lines)

    def _local_template_from_input(self, llm_input: Dict[str, Any]) -> str:
        return json.dumps(llm_input, ensure_ascii=False, indent=2)

    def _local_template_answer_from_input(self, llm_input: Dict[str, Any]) -> str:
        return json.dumps(llm_input, ensure_ascii=False, indent=2)

    def _local_fallback_with_reason(self, reason: str, fallback: str) -> str:
        return (
            "Remote LLM was not used.\n"
            f"Reason: {reason}\n\n"
            "Local fallback output:\n"
            f"{fallback}"
        )

    def _clean_model_text(self, text: str) -> str:
        cleaned = text.strip()
        cleaned = cleaned.replace("**", "")
        cleaned = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", cleaned)
        cleaned = re.sub(r"(?m)^\s*[-*_]{3,}\s*$", "", cleaned)
        cleaned = re.sub(r"(?m)^\s*[-*]\s+", "", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()
