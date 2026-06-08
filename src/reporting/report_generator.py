from __future__ import annotations

import json
from typing import Any, Dict

from ..config import AgentConfig
from ..schemas import DailyBrief


class ReportGenerator:
    def __init__(self, config: AgentConfig):
        self.config = config

    def build_llm_input(self, brief: DailyBrief) -> Dict[str, Any]:
        return {
            "as_of": brief.as_of.isoformat(),
            "portfolio_summary": {
                "total_market_value": brief.portfolio_snapshot.total_market_value,
                "total_cost": brief.portfolio_snapshot.total_cost,
                "cash": brief.portfolio_snapshot.cash,
                "total_return": brief.portfolio_metrics.total_return,
                "largest_position_weight": brief.portfolio_metrics.largest_position_weight,
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
                return llm_input, remote
        return llm_input, self._local_template_report(brief)

    def answer_question(self, brief: DailyBrief, question: str) -> tuple[Dict[str, Any], str]:
        llm_input = self.build_llm_input(brief)
        llm_input["user_question"] = question
        if self.config.llm.provider != "local_template" and self.config.llm.api_key:
            remote = self._try_remote_answer(llm_input, question)
            if remote:
                return llm_input, remote
        return llm_input, self._local_template_answer(brief, question)

    def _try_remote_report(self, llm_input: Dict[str, Any]) -> str | None:
        try:
            from openai import OpenAI
        except ImportError:
            return None

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
                            "Write in Chinese."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(llm_input, ensure_ascii=False, indent=2),
                    },
                ],
                temperature=0.2,
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            return f"Remote LLM report failed, local fallback used.\n\n{exc}\n\n{self._local_template_from_input(llm_input)}"

    def _try_remote_answer(self, llm_input: Dict[str, Any], question: str) -> str | None:
        try:
            from openai import OpenAI
        except ImportError:
            return None

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
                            "If the data is insufficient, say what is missing. Write in Chinese when the user writes Chinese."
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
            return response.choices[0].message.content or ""
        except Exception as exc:
            return f"Remote LLM answer failed, local fallback used.\n\n{exc}\n\n{self._local_template_answer_from_input(llm_input)}"

    def _local_template_report(self, brief: DailyBrief) -> str:
        total_return = brief.portfolio_metrics.total_return
        total_return_text = "unknown" if total_return is None else f"{total_return:.2%}"
        themes = "\n".join(
            f"- #{item.rank or '-'} [{item.severity.value}] {item.title} "
            f"({item.priority_score:.1f}/100): {item.summary}"
            for item in brief.risk_themes
        ) or "- No major risk theme."
        signals = "\n".join(f"- [{item.severity.value}] {item.target}: {item.summary}" for item in brief.signals) or "- No signal."
        candidates = "\n".join(f"- {item.target}: {item.summary}" for item in brief.strategy_candidates) or "- No strategy candidate."
        news = "\n".join(
            f"- {item.theme_key}: impact={item.news_impact:.1f}/100, exposure={item.portfolio_exposure:.1%}, "
            f"affected={', '.join(item.affected_symbols) or 'none'}"
            for item in sorted(brief.news_impacts, key=lambda impact: impact.news_impact, reverse=True)[:5]
        ) or "- No portfolio-weighted news impact."

        return (
            "Local Daily Portfolio Brief\n\n"
            f"Total market value: {brief.portfolio_snapshot.total_market_value:.2f} {brief.portfolio_snapshot.base_currency}\n"
            f"Total return: {total_return_text}\n"
            f"Largest position weight: {(brief.portfolio_metrics.largest_position_weight or 0):.2%}\n\n"
            "Ranked risk themes:\n"
            f"{themes}\n\n"
            "Triggered signals:\n"
            f"{signals}\n\n"
            "Strategy candidates:\n"
            f"{candidates}\n\n"
            "News impact layer:\n"
            f"{news}\n\n"
            f"Disclaimer: {brief.disclaimer}"
        )

    def _local_template_answer(self, brief: DailyBrief, question: str) -> str:
        total_return = brief.portfolio_metrics.total_return
        total_return_text = "unknown" if total_return is None else f"{total_return:.2%}"
        signal_text = "\n".join(
            f"- [{item.severity.value}] {item.target}: {item.summary}"
            for item in brief.signals[:5]
        ) or "- No triggered signal."
        theme_text = "\n".join(
            f"- #{item.rank or '-'} [{item.severity.value}] {item.title} "
            f"({item.priority_score:.1f}/100): {item.summary}"
            for item in brief.risk_themes[:5]
        ) or "- No major risk theme."
        candidate_text = "\n".join(
            f"- {item.target}: {item.summary}"
            for item in brief.strategy_candidates[:5]
        ) or "- No strategy candidate."
        return (
            f"Question: {question}\n\n"
            "Based on the current local DailyBrief:\n"
            f"- Portfolio value: {brief.portfolio_snapshot.total_market_value:.2f} {brief.portfolio_snapshot.base_currency}\n"
            f"- Total return: {total_return_text}\n"
            f"- Largest position weight: {(brief.portfolio_metrics.largest_position_weight or 0):.2%}\n\n"
            "Priority risk themes:\n"
            f"{theme_text}\n\n"
            "Mapped rule signals:\n"
            f"{signal_text}\n\n"
            "Strategy candidates:\n"
            f"{candidate_text}\n\n"
            "This answer comes from local structured analytics, not direct raw-data LLM interpretation."
        )

    def _local_template_from_input(self, llm_input: Dict[str, Any]) -> str:
        return json.dumps(llm_input, ensure_ascii=False, indent=2)

    def _local_template_answer_from_input(self, llm_input: Dict[str, Any]) -> str:
        return json.dumps(llm_input, ensure_ascii=False, indent=2)
