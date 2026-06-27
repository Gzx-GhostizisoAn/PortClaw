from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Any, Iterable, List
from html import unescape
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from uuid import uuid4

import requests
from bs4 import BeautifulSoup

from ..config import AgentConfig
from ..schemas import (
    NewsEvent,
    NewsEventCategory,
    NewsEventType,
    NewsImpact,
    NewsItem,
    PortfolioSnapshot,
)


CRAWLER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
}


EVENT_RULES = [
    {
        "event_type": NewsEventType.MACRO_RATES,
        "category": NewsEventCategory.MACRO,
        "keywords": {"fed", "federal reserve", "rate", "rates", "yield", "treasury", "central bank"},
        "theme_keys": ["macro_risk", "volatility_risk"],
    },
    {
        "event_type": NewsEventType.MACRO_INFLATION,
        "category": NewsEventCategory.MACRO,
        "keywords": {"inflation", "cpi", "ppi", "prices", "deflation"},
        "theme_keys": ["macro_risk", "volatility_risk"],
    },
    {
        "event_type": NewsEventType.MACRO_USD,
        "category": NewsEventCategory.MACRO,
        "keywords": {"dollar", "usd", "currency", "fx"},
        "theme_keys": ["macro_risk"],
    },
    {
        "event_type": NewsEventType.MACRO_OIL,
        "category": NewsEventCategory.MACRO,
        "keywords": {"oil", "crude", "opec", "energy prices"},
        "theme_keys": ["macro_risk", "volatility_risk"],
    },
    {
        "event_type": NewsEventType.INDUSTRY_POLICY,
        "category": NewsEventCategory.INDUSTRY,
        "keywords": {"export control", "restriction", "sanction", "tariff", "regulation", "policy", "ban"},
        "theme_keys": ["news_risk", "macro_risk"],
    },
    {
        "event_type": NewsEventType.INDUSTRY_DEMAND,
        "category": NewsEventCategory.INDUSTRY,
        "keywords": {"demand", "orders", "shipment", "inventory", "cycle"},
        "theme_keys": ["news_risk", "volatility_risk"],
    },
    {
        "event_type": NewsEventType.INDUSTRY_SUPPLY_CHAIN,
        "category": NewsEventCategory.INDUSTRY,
        "keywords": {"supply chain", "shortage", "capacity", "foundry", "fab", "supplier"},
        "theme_keys": ["news_risk", "volatility_risk"],
    },
    {
        "event_type": NewsEventType.COMPANY_EARNINGS,
        "category": NewsEventCategory.COMPANY,
        "keywords": {"earnings", "revenue", "profit", "margin", "eps", "results"},
        "theme_keys": ["news_risk", "volatility_risk"],
    },
    {
        "event_type": NewsEventType.COMPANY_GUIDANCE,
        "category": NewsEventCategory.COMPANY,
        "keywords": {"guidance", "forecast", "outlook", "warning", "cut"},
        "theme_keys": ["news_risk", "volatility_risk"],
    },
    {
        "event_type": NewsEventType.COMPANY_REGULATORY,
        "category": NewsEventCategory.COMPANY,
        "keywords": {"sec", "probe", "investigation", "lawsuit", "antitrust", "recall"},
        "theme_keys": ["news_risk", "liquidity_risk"],
    },
    {
        "event_type": NewsEventType.COMPANY_PRODUCT,
        "category": NewsEventCategory.COMPANY,
        "keywords": {"launch", "product", "chip", "ai", "gpu", "platform", "approval"},
        "theme_keys": ["news_risk", "volatility_risk"],
    },
    {
        "event_type": NewsEventType.COMPANY_SENTIMENT,
        "category": NewsEventCategory.COMPANY,
        "keywords": {
            "bearish",
            "concern",
            "controversy",
            "downgrade",
            "fraud",
            "negative",
            "plunge",
            "sell-off",
            "slump",
            "weak demand",
        },
        "theme_keys": ["news_risk", "volatility_risk"],
    },
]


HIGH_SEVERITY_KEYWORDS = {
    "ban",
    "blocked",
    "restriction",
    "sanction",
    "probe",
    "investigation",
    "lawsuit",
    "default",
    "bankruptcy",
    "miss",
    "cut",
    "warning",
    "fraud",
    "plunge",
    "sell-off",
}

MEDIUM_SEVERITY_KEYWORDS = {
    "tariff",
    "regulation",
    "recall",
    "shortage",
    "downgrade",
    "delay",
    "weak",
    "slows",
    "concern",
    "controversy",
}

SECTOR_KEYWORDS = {
    "Technology": {"ai", "chip", "semiconductor", "software", "cloud", "gpu", "foundry", "export control"},
    "Financials": {"bank", "insurance", "credit", "loan", "deposit", "capital ratio"},
    "Energy": {"oil", "gas", "crude", "opec", "refinery"},
    "Healthcare": {"drug", "fda", "clinical", "biotech", "medicare"},
    "Consumer": {"retail", "consumer", "spending", "inventory"},
}


class NewsFetcher:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.last_status: dict[str, object] = {
            "component": "news",
            "provider": config.market_data.provider,
            "status": "not_requested",
            "errors": [],
        }

    def fetch(self, symbols: Iterable[str], limit_per_symbol: int = 5) -> List[NewsItem]:
        positions = [{"symbol": str(symbol).strip().upper()} for symbol in symbols if str(symbol).strip()]
        return self.fetch_portfolio_news(positions, limit=max(1, limit_per_symbol) * max(1, len(positions)))

    def fetch_portfolio_news(self, positions: Iterable[dict[str, Any]], limit: int = 12, lookback: str | None = None) -> List[NewsItem]:
        positions = list(positions)
        provider = self.config.market_data.provider
        news_provider = getattr(getattr(self.config, "news", None), "provider", "auto") or "auto"
        lookback = self._normalize_lookback(lookback or getattr(getattr(self.config, "news", None), "lookback", "7d"))
        self.last_status = {
            "component": "news",
            "provider": provider,
            "news_provider": news_provider,
            "lookback": lookback,
            "status": "not_requested",
            "errors": [],
            "adapter": None,
            "fallback_used": False,
        }
        adapters = {
            "yahoo": lambda items, count: self._fetch_yfinance_portfolio_news(items, count, lookback),
            "tushare": lambda items, count: self._fetch_tushare_portfolio_news(items, count, lookback),
        }
        errors: list[str] = []

        if news_provider == "crawler":
            return self._fetch_web_crawler_portfolio_news(positions, limit, lookback)

        primary = adapters.get(provider)
        if primary:
            items = primary(positions, limit)
            if items:
                self.last_status.update({"status": "ok", "adapter": provider, "fallback_used": False, "item_count": len(items)})
                return items
            errors.extend(str(item) for item in self.last_status.get("errors", []))
        else:
            errors.append(f"{provider} does not have a dedicated news adapter yet")

        if news_provider == "provider":
            self.last_status.update(
                {
                    "status": "empty" if not errors else "error",
                    "adapter": None,
                    "fallback_used": False,
                    "errors": errors[:8],
                    "item_count": 0,
                }
            )
            return []

        for adapter_name, adapter in adapters.items():
            if adapter_name == provider:
                continue
            if adapter_name == "tushare":
                continue
            items = adapter(positions, limit)
            if items:
                self.last_status.update(
                    {
                        "status": "fallback_ok",
                        "provider": provider,
                        "adapter": adapter_name,
                        "fallback_used": True,
                        "errors": errors[:8],
                        "item_count": len(items),
                    }
                )
                return items
            errors.extend(str(item) for item in self.last_status.get("errors", []))

        crawler_items = self._fetch_web_crawler_portfolio_news(positions, limit, lookback, fallback_errors=errors)
        if crawler_items:
            return crawler_items

        self.last_status.update(
            {
                "status": "empty" if not errors else "error",
                "provider": provider,
                "adapter": None,
                "fallback_used": False,
                "errors": errors[:8],
                "item_count": 0,
            }
        )
        return []

    def _normalize_lookback(self, value: str | None) -> str:
        if value in {"today", "7d", "1m", "6m"}:
            return str(value)
        return "7d"

    def _lookback_days(self, lookback: str) -> int:
        return {"today": 1, "7d": 7, "1m": 30, "6m": 183}.get(lookback, 7)

    def _lookback_start(self, lookback: str) -> datetime:
        return datetime.utcnow() - timedelta(days=self._lookback_days(lookback))

    def _filter_by_lookback(self, items: list[NewsItem], lookback: str) -> list[NewsItem]:
        start = self._lookback_start(lookback)
        return [item for item in items if item.timestamp >= start]

    def _lookback_query_hint(self, lookback: str, source: str) -> str:
        if source == "baidu":
            return {"today": " 今日", "7d": " 近7天", "1m": " 近一个月", "6m": " 近半年"}.get(lookback, "")
        return {"today": " today", "7d": " past week", "1m": " past month", "6m": " past six months"}.get(lookback, "")

    def _fetch_tushare_portfolio_news(self, positions: Iterable[dict[str, Any]], limit: int, lookback: str) -> List[NewsItem]:
        token = self.config.market_data.api_key
        if not token:
            self.last_status.update({"status": "error", "errors": ["Tushare token is required"], "item_count": 0})
            return []
        try:
            import tushare as ts
        except ImportError:
            self.last_status.update({"status": "error", "errors": ["tushare is not installed"], "item_count": 0})
            return []

        portfolio_terms = self._portfolio_terms(positions)
        if not portfolio_terms:
            self.last_status.update({"status": "empty", "errors": ["portfolio has no symbols"], "item_count": 0})
            return []

        start_date = self._lookback_start(lookback).date().strftime("%Y%m%d")
        end_date = datetime.utcnow().date().strftime("%Y%m%d")
        output: list[NewsItem] = []
        errors: list[str] = []
        seen: set[tuple[str, str | None]] = set()
        try:
            pro = ts.pro_api(token)
        except Exception as exc:
            self.last_status.update({"status": "error", "errors": [str(exc)], "item_count": 0})
            return []

        global_frames = self._tushare_global_news_frames(pro, start_date, end_date, errors)
        for symbol, terms in portfolio_terms.items():
            frames = self._tushare_announcement_frames(pro, symbol, start_date, end_date, errors) + global_frames
            for frame in frames:
                for raw in frame:
                    item = self._normalize_tushare_news_item(raw, symbol)
                    text = f"{item.title} {item.content}".lower()
                    matched_symbols = [
                        item_symbol
                        for item_symbol, item_terms in portfolio_terms.items()
                        if any(term and term.lower() in text for term in item_terms)
                    ]
                    if symbol not in matched_symbols and not any(term and term.lower() in text for term in terms):
                        continue
                    item.symbols = sorted(set(matched_symbols or [symbol]))
                    key = (item.title, item.url)
                    if key in seen:
                        continue
                    seen.add(key)
                    output.append(item)

        output = sorted(output, key=lambda item: item.timestamp, reverse=True)[:limit]
        if output:
            self.last_status.update({"status": "ok" if not errors else "partial", "errors": errors[:8], "item_count": len(output)})
        else:
            self.last_status.update({"status": "empty" if not errors else "error", "errors": errors[:8], "item_count": 0})
        return output

    def _portfolio_terms(self, positions: Iterable[dict[str, Any]]) -> dict[str, set[str]]:
        output: dict[str, set[str]] = {}
        for item in positions:
            symbol = str(item.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            code = symbol.split(".", 1)[0]
            terms = {symbol, code}
            for key in ("name", "sector"):
                value = str(item.get(key) or "").strip()
                if value:
                    terms.add(value)
            output[symbol] = terms
        return output

    def _tushare_announcement_frames(self, pro: Any, symbol: str, start_date: str, end_date: str, errors: list[str]) -> list[list[dict[str, Any]]]:
        frames: list[list[dict[str, Any]]] = []
        for method_name, kwargs in (("anns", {"ts_code": symbol, "start_date": start_date, "end_date": end_date}),):
            frame = self._query_tushare_frame(pro, method_name, kwargs, errors)
            if frame is not None and not getattr(frame, "empty", True):
                frames.append(frame.head(80).to_dict("records"))
        return frames

    def _tushare_global_news_frames(self, pro: Any, start_date: str, end_date: str, errors: list[str]) -> list[list[dict[str, Any]]]:
        frames: list[list[dict[str, Any]]] = []
        for method_name, kwargs in (
            ("news", {"src": "sina", "start_date": start_date, "end_date": end_date}),
            ("major_news", {"src": "sina", "start_date": start_date, "end_date": end_date}),
        ):
            frame = self._query_tushare_frame(pro, method_name, kwargs, errors)
            if frame is not None and not getattr(frame, "empty", True):
                frames.append(frame.head(160).to_dict("records"))
        return frames

    def _query_tushare_frame(self, pro: Any, method_name: str, kwargs: dict[str, Any], errors: list[str]) -> Any | None:
        try:
            method = getattr(pro, method_name, None)
            if method:
                frame = method(**kwargs)
            elif hasattr(pro, "query"):
                frame = pro.query(method_name, **kwargs)
            else:
                return None
        except Exception as exc:
            errors.append(f"{method_name}: {exc}")
            return None
        return frame

    def _normalize_tushare_news_item(self, raw: dict[str, Any], symbol: str) -> NewsItem:
        title = raw.get("title") or raw.get("ann_title") or raw.get("headline") or raw.get("name") or ""
        content = raw.get("content") or raw.get("summary") or raw.get("ann_desc") or raw.get("abstract") or ""
        timestamp_raw = raw.get("datetime") or raw.get("pub_time") or raw.get("ann_date") or raw.get("trade_date") or raw.get("date")
        timestamp = self._parse_tushare_timestamp(timestamp_raw)
        url = raw.get("url") or raw.get("ann_url")
        source = raw.get("src") or raw.get("source") or "tushare"
        return NewsItem(
            title=str(title),
            content=str(content),
            source=str(source),
            timestamp=timestamp,
            symbols=[symbol],
            url=str(url) if url else None,
            metadata={"provider": "tushare"},
        )

    def _parse_tushare_timestamp(self, value: Any) -> datetime:
        if value in {None, ""}:
            return datetime.utcnow()
        text = str(value).strip()
        for fmt in ("%Y%m%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return datetime.utcnow()

    def _fetch_web_crawler_portfolio_news(
        self,
        positions: Iterable[dict[str, Any]],
        limit: int,
        lookback: str,
        fallback_errors: list[str] | None = None,
    ) -> List[NewsItem]:
        output: list[NewsItem] = []
        errors = list(fallback_errors or [])
        seen: set[tuple[str, str | None]] = set()
        for position in positions:
            source = "baidu" if self._is_a_share_position(position) else "yahoo"
            items: list[NewsItem] = []
            queries = [
                self._crawler_query(position, source, lookback),
                self._crawler_query(position, source, lookback, include_hint=False),
            ]
            for query in dict.fromkeys(queries):
                try:
                    items = self._search_baidu_news(query, position, max(1, limit // 2)) if source == "baidu" else self._search_yahoo_news(query, position, max(1, limit // 2))
                except Exception as exc:
                    errors.append(f"{source} crawler {query}: {exc}")
                    continue
                if items:
                    break
            if not items and source == "baidu":
                errors.append(f"baidu crawler {queries[0]}: no parseable result, trying yahoo fallback")
                yahoo_queries = [
                    self._crawler_query(position, "yahoo", lookback),
                    self._crawler_query(position, "yahoo", lookback, include_hint=False),
                ]
                for yahoo_query in dict.fromkeys(yahoo_queries):
                    try:
                        items = self._search_yahoo_news(yahoo_query, position, max(1, limit // 2))
                    except Exception as exc:
                        errors.append(f"yahoo crawler fallback {yahoo_query}: {exc}")
                        continue
                    if items:
                        break
            for item in items:
                key = (item.title, item.url)
                if key in seen:
                    continue
                seen.add(key)
                output.append(item)
            if len(output) >= limit:
                break
        output = sorted(output, key=lambda item: item.timestamp, reverse=True)[:limit]
        self.last_status.update(
            {
                "status": "crawler_ok" if output else "empty" if not errors else "error",
                "adapter": "crawler",
                "fallback_used": bool(fallback_errors),
                "errors": errors[:8],
                "item_count": len(output),
            }
        )
        return output

    def _is_a_share_position(self, position: dict[str, Any]) -> bool:
        symbol = str(position.get("symbol") or "").strip().upper()
        if symbol.endswith((".SH", ".SZ", ".BJ")):
            return True
        return symbol.isdigit() and len(symbol) == 6

    def _crawler_query(self, position: dict[str, Any], source: str, lookback: str, include_hint: bool = True) -> str:
        name = self._clean_text(str(position.get("name") or ""))
        symbol = str(position.get("symbol") or "").strip().upper()
        identity = " ".join(part for part in [symbol, name] if part).strip() or symbol or name
        hint = self._lookback_query_hint(lookback, source) if include_hint else ""
        if source == "baidu":
            return f"{identity} 新闻{hint}"
        return f"{identity} stock news{hint}"

    def _search_yahoo_news(self, query: str, position: dict[str, Any], limit: int) -> list[NewsItem]:
        url = f"https://news.search.yahoo.com/search?p={quote_plus(query)}"
        soup = BeautifulSoup(self._fetch_crawler_html(url), "html.parser")
        nodes = []
        for selector in ("li div.NewsArticle", "div.NewsArticle", "ol.searchCenterMiddle li", "div#web ol li"):
            nodes = soup.select(selector)
            if nodes:
                break
        lookback = self._lookback_from_query(query)
        return self._parse_search_nodes("yahoo_crawler", query, position, nodes, limit, lookback)

    def _search_baidu_news(self, query: str, position: dict[str, Any], limit: int) -> list[NewsItem]:
        urls = [
            f"https://www.baidu.com/s?tn=news&rtt=1&bsst=1&cl=2&wd={quote_plus(query)}",
            f"https://m.baidu.com/s?word={quote_plus(query)}&tn=bdwns",
        ]
        for url in urls:
            soup = BeautifulSoup(self._fetch_crawler_html(url), "html.parser")
            nodes = soup.select("div.result, div.result-op, div.c-container, div.c-result")
            lookback = self._lookback_from_query(query)
            items = self._parse_search_nodes("baidu_crawler", query, position, nodes, limit, lookback)
            if items:
                return items
        return []

    def _parse_search_nodes(self, source: str, query: str, position: dict[str, Any], nodes: list[Any], limit: int, lookback: str) -> list[NewsItem]:
        output: list[NewsItem] = []
        symbol = str(position.get("symbol") or "").strip().upper()
        start = self._lookback_start(lookback)
        now = datetime.utcnow()
        for node in nodes:
            link = self._best_news_link(node)
            if not link:
                continue
            href = self._direct_url(link.get("href") or "")
            title = self._clean_text(link.get_text(" "))
            if not title or title.startswith("http"):
                title = self._title_from_node_text(node)
            if not self._looks_like_news(title, href):
                continue
            snippet_node = node.select_one(".s-desc, .fc-falcon, .c-font-normal, .c-span-last, .content-right_8Zs40, .c-abstract, p")
            snippet = self._clean_text(snippet_node.get_text(" ") if snippet_node else node.get_text(" "))
            publisher_node = node.select_one(".s-source, .mr-5, cite, .c-color-gray, .c-color-gray2, .news-source_Xj4Dv")
            publisher = self._clean_text(publisher_node.get_text(" ") if publisher_node else source)
            timestamp = self._parse_crawler_timestamp(" ".join([title, snippet, publisher, self._clean_text(node.get_text(" "))]), now)
            if timestamp is None:
                continue
            if timestamp < start or timestamp > now + timedelta(hours=6):
                continue
            output.append(
                NewsItem(
                    title=title,
                    content=snippet,
                    source=publisher or source,
                    timestamp=timestamp,
                    symbols=[symbol] if symbol else [],
                    url=href,
                    metadata={"provider": source, "query": query, "timestamp_source": "crawler_text"},
                )
            )
            if len(output) >= limit:
                break
        return output

    def _lookback_from_query(self, query: str) -> str:
        text = query.lower()
        if "今日" in query or "today" in text:
            return "today"
        if "近7天" in query or "past week" in text:
            return "7d"
        if "近一个月" in query or "past month" in text:
            return "1m"
        if "近半年" in query or "past six months" in text:
            return "6m"
        return getattr(getattr(self.config, "news", None), "lookback", "7d") or "7d"

    def _parse_crawler_timestamp(self, text: str, now: datetime) -> datetime | None:
        cleaned = self._clean_text(text)
        for pattern, fmt in (
            (r"(20\d{2})年(\d{1,2})月(\d{1,2})日", None),
            (r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", None),
        ):
            match = re.search(pattern, cleaned)
            if match:
                year, month, day = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
                return datetime(year, month, day)

        match = re.search(r"(?<!\d)(\d{1,2})月(\d{1,2})日", cleaned)
        if match:
            month, day = int(match.group(1)), int(match.group(2))
            candidate = datetime(now.year, month, day)
            if candidate > now + timedelta(days=1):
                candidate = datetime(now.year - 1, month, day)
            return candidate

        match = re.search(r"(\d{1,3})\s*(?:天|日)\s*前", cleaned)
        if match:
            return now - timedelta(days=int(match.group(1)))
        match = re.search(r"(\d{1,3})\s*(?:小时|小時)\s*前", cleaned)
        if match:
            return now - timedelta(hours=int(match.group(1)))
        if "前天" in cleaned:
            return now - timedelta(days=2)
        if "昨天" in cleaned or "昨日" in cleaned:
            return now - timedelta(days=1)
        if "今天" in cleaned or "今日" in cleaned:
            return now

        match = re.search(r"(\d{1,3})\s+days?\s+ago", cleaned, flags=re.IGNORECASE)
        if match:
            return now - timedelta(days=int(match.group(1)))
        match = re.search(r"(\d{1,3})\s+hours?\s+ago", cleaned, flags=re.IGNORECASE)
        if match:
            return now - timedelta(hours=int(match.group(1)))
        if re.search(r"\byesterday\b", cleaned, flags=re.IGNORECASE):
            return now - timedelta(days=1)
        if re.search(r"\btoday\b", cleaned, flags=re.IGNORECASE):
            return now

        month_names = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
        match = re.search(rf"\b({month_names})\.?\s+(\d{{1,2}}),?\s+(20\d{{2}})\b", cleaned, flags=re.IGNORECASE)
        if match:
            month_lookup = {
                "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
            }
            month = month_lookup[match.group(1).lower().rstrip(".")]
            return datetime(int(match.group(3)), month, int(match.group(2)))
        return None

    def _best_news_link(self, node: Any) -> Any | None:
        preferred = node.select_one("h4 a, h3 a")
        if preferred and self._looks_like_news(self._clean_text(preferred.get_text(" ")), self._direct_url(preferred.get("href") or "")):
            return preferred
        for link in node.select("a"):
            href = self._direct_url(link.get("href") or "")
            if self._looks_like_news(self._clean_text(link.get_text(" ")), href) or self._external_news_url(href):
                return link
        return None

    def _title_from_node_text(self, node: Any) -> str:
        text = self._clean_text(node.get_text(" "))
        text = re.sub(r"总结全网\\d+篇结果.*?(?=贵州|[A-Z][A-Za-z])", "", text)
        text = re.sub(r"\\d{4}年\\d{1,2}月\\d{1,2}日", " ", text)
        parts = re.split(r"\\s{2,}| - | _ | \\| |。", text)
        for part in parts:
            part = self._clean_text(part)
            if 8 <= len(part) <= 80 and not part.startswith(("大家还在搜", "点击", "暂停", "收听")):
                return part
        return text[:80]

    def _external_news_url(self, url: str) -> bool:
        host = urlparse(url).netloc.lower()
        return bool(host) and not any(host.endswith(blocked) for blocked in ("baidu.com", "yahoo.com"))

    def _fetch_crawler_html(self, url: str) -> str:
        response = requests.get(url, headers=CRAWLER_HEADERS, timeout=12)
        response.raise_for_status()
        return response.text

    def _clean_text(self, value: str | None) -> str:
        text = unescape(value or "")
        return re.sub(r"\s+", " ", text).strip()

    def _direct_url(self, value: str) -> str:
        if not value:
            return ""
        parsed = urlparse(value)
        query = parse_qs(parsed.query)
        for key in ("target", "url", "u"):
            if key in query and query[key]:
                return unquote(query[key][0])
        match = re.search(r"/RU=([^/]+)/", value)
        if match:
            return unquote(match.group(1))
        return value

    def _looks_like_news(self, title: str, url: str) -> bool:
        if len(self._clean_text(title)) < 6:
            return False
        blocked_hosts = {"top.baidu.com", "www.baidu.com", "m.baidu.com", "search.yahoo.com", "news.search.yahoo.com"}
        return urlparse(url).netloc.lower() not in blocked_hosts

    def _fetch_yfinance_portfolio_news(self, positions: Iterable[dict[str, Any]], limit: int, lookback: str) -> List[NewsItem]:
        symbol_map = self._yfinance_symbol_map(positions)
        if not symbol_map:
            self.last_status.update({"status": "empty", "errors": ["portfolio has no symbols"], "item_count": 0})
            return []
        items = self._fetch_yfinance_news(symbol_map.keys(), max(1, limit // max(1, len(symbol_map))))
        for item in items:
            item.symbols = [symbol_map.get(symbol, symbol) for symbol in item.symbols]
            item.metadata["adapter"] = "yfinance"
        output = sorted(self._filter_by_lookback(items, lookback), key=lambda item: item.timestamp, reverse=True)[:limit]
        if output and not self.last_status.get("errors"):
            self.last_status.update({"status": "ok", "errors": [], "item_count": len(output)})
        elif not output and not self.last_status.get("errors"):
            self.last_status.update({"status": "empty", "errors": ["yfinance returned no matching news"], "item_count": 0})
        return output

    def _yfinance_symbol_map(self, positions: Iterable[dict[str, Any]]) -> dict[str, str]:
        output: dict[str, str] = {}
        for item in positions:
            original = str(item.get("symbol") or "").strip().upper()
            if not original:
                continue
            for candidate in self._yfinance_symbol_candidates(original):
                output[candidate] = original
        return output

    def _yfinance_symbol_candidates(self, symbol: str) -> list[str]:
        if symbol.endswith(".SH"):
            return [symbol.replace(".SH", ".SS")]
        if symbol.endswith(".SZ"):
            return [symbol]
        if symbol.endswith(".BJ"):
            return [symbol]
        if "." in symbol:
            return [symbol]
        if symbol.isdigit() and len(symbol) == 6:
            if symbol.startswith(("5", "6", "9")):
                return [f"{symbol}.SS"]
            if symbol.startswith(("0", "1", "2", "3")):
                return [f"{symbol}.SZ"]
        return [symbol]

    def _fetch_yfinance_news(self, symbols: Iterable[str], limit_per_symbol: int) -> List[NewsItem]:
        try:
            import yfinance as yf
        except ImportError:
            self.last_status.update({"status": "error", "errors": ["yfinance is not installed"], "item_count": 0})
            return []

        output: list[NewsItem] = []
        seen: set[tuple[str, str | None]] = set()
        errors: list[str] = []
        for symbol in sorted(set(symbols)):
            try:
                raw_items = yf.Ticker(symbol).news or []
            except Exception as exc:
                errors.append(f"{symbol}: {exc}")
                continue
            for raw in raw_items[:limit_per_symbol]:
                item = self._normalize_yfinance_item(raw, symbol)
                key = (item.title, item.url)
                if key in seen:
                    continue
                seen.add(key)
                output.append(item)
        if errors:
            self.last_status.update({"status": "partial" if output else "error", "errors": errors, "item_count": len(output)})
        return output

    def _normalize_yfinance_item(self, raw: dict, symbol: str) -> NewsItem:
        content_payload = raw.get("content") if isinstance(raw.get("content"), dict) else {}
        content = raw.get("summary") or content_payload.get("summary") or content_payload.get("description") or ""
        title = raw.get("title") or content_payload.get("title") or ""
        timestamp = raw.get("providerPublishTime") or raw.get("pubDate")
        if isinstance(timestamp, (int, float)):
            published_at = datetime.utcfromtimestamp(timestamp)
        else:
            published_at = datetime.utcnow()
        return NewsItem(
            title=str(title),
            content=str(content),
            source=str(raw.get("publisher") or raw.get("source") or "yfinance"),
            timestamp=published_at,
            symbols=[symbol],
            url=raw.get("link") or raw.get("url") or content_payload.get("canonicalUrl", {}).get("url"),
            metadata={"provider": "yfinance"},
        )


class NewsEventClassifier:
    def classify(self, items: List[NewsItem]) -> List[NewsEvent]:
        events: list[NewsEvent] = []
        for index, item in enumerate(items):
            text = self._text(item)
            matched = False
            for rule in EVENT_RULES:
                keywords = sorted(keyword for keyword in rule["keywords"] if keyword in text)
                if not keywords:
                    continue
                events.append(
                    NewsEvent(
                        event_id=f"event_{uuid4().hex}",
                        event_type=rule["event_type"],
                        category=rule["category"],
                        title=item.title,
                        summary=(item.content or item.title)[:500],
                        severity_score=self._severity(text),
                        theme_keys=list(rule["theme_keys"]),
                        symbols=item.symbols,
                        keywords=keywords,
                        source_news_index=index,
                    )
                )
                matched = True
            if not matched:
                events.append(
                    NewsEvent(
                        event_id=f"event_{uuid4().hex}",
                        event_type=NewsEventType.UNKNOWN,
                        category=NewsEventCategory.UNKNOWN,
                        title=item.title,
                        summary=(item.content or item.title)[:500],
                        severity_score=0.25,
                        theme_keys=["news_risk"],
                        symbols=item.symbols,
                        source_news_index=index,
                    )
                )
        return events

    def _severity(self, text: str) -> float:
        if any(keyword in text for keyword in HIGH_SEVERITY_KEYWORDS):
            return 0.90
        if any(keyword in text for keyword in MEDIUM_SEVERITY_KEYWORDS):
            return 0.65
        return 0.40

    def _text(self, item: NewsItem) -> str:
        return f"{item.title} {item.content}".lower()


class NewsImpactAnalyzer:
    def analyze(self, snapshot: PortfolioSnapshot, events: List[NewsEvent]) -> List[NewsImpact]:
        impacts: list[NewsImpact] = []
        event_cluster_counts = self._event_cluster_counts(events)
        for event in events:
            exposure, affected_symbols, rationale = self._portfolio_exposure(snapshot, event)
            relevance = 1.0 if affected_symbols else 0.25 if event.category == NewsEventCategory.MACRO else 0.0
            cluster_count = self._cluster_count(event, event_cluster_counts)
            base_impact = round(event.severity_score * exposure * relevance * 100, 2)
            amplification_factor, amplification_reasons = self._amplification(event, exposure, cluster_count)
            news_impact = round(min(100.0, base_impact * amplification_factor), 2)
            for theme_key in event.theme_keys:
                impacts.append(
                    NewsImpact(
                        impact_id=f"impact_{uuid4().hex}",
                        event_id=event.event_id,
                        theme_key=theme_key,
                        event_severity=event.severity_score,
                        portfolio_exposure=exposure,
                        relevance_score=relevance,
                        base_impact=base_impact,
                        amplification_factor=amplification_factor,
                        news_impact=news_impact,
                        affected_symbols=affected_symbols,
                        rationale=self._impact_rationale(rationale, amplification_reasons),
                        metadata={
                            "cluster_count": cluster_count,
                            "amplification_reasons": amplification_reasons,
                        },
                    )
                )
        return impacts

    def _event_cluster_counts(self, events: List[NewsEvent]) -> dict[tuple[str, str], int]:
        counts: dict[tuple[str, str], int] = {}
        for event in events:
            symbol_key = ",".join(sorted(symbol.upper() for symbol in event.symbols)) or "macro_or_unknown"
            key = (event.event_type.value, symbol_key)
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _cluster_count(self, event: NewsEvent, counts: dict[tuple[str, str], int]) -> int:
        symbol_key = ",".join(sorted(symbol.upper() for symbol in event.symbols)) or "macro_or_unknown"
        return counts.get((event.event_type.value, symbol_key), 1)

    def _amplification(self, event: NewsEvent, exposure: float, cluster_count: int) -> tuple[float, list[str]]:
        factor = 1.0
        reasons: list[str] = []
        severity_boost = round((event.severity_score**2) * 0.60, 3)
        if severity_boost:
            factor += severity_boost
            reasons.append(f"severity convexity +{severity_boost:.2f}")
        exposure_boost = round((exposure**2) * 0.50, 3)
        if exposure_boost:
            factor += exposure_boost
            reasons.append(f"portfolio exposure convexity +{exposure_boost:.2f}")
        if cluster_count > 1:
            cluster_boost = min(0.75, (cluster_count - 1) * 0.25)
            factor += cluster_boost
            reasons.append(f"similar event cluster +{cluster_boost:.2f}")
        if event.event_type == NewsEventType.COMPANY_SENTIMENT:
            factor += 0.30
            reasons.append("negative sentiment event +0.30")
        capped = min(2.5, factor)
        if capped < factor:
            reasons.append("amplification capped at 2.50")
        return round(capped, 2), reasons

    def _impact_rationale(self, base_rationale: str, amplification_reasons: list[str]) -> str:
        if not amplification_reasons:
            return base_rationale
        return f"{base_rationale} Nonlinear amplification: {', '.join(amplification_reasons)}."

    def _portfolio_exposure(self, snapshot: PortfolioSnapshot, event: NewsEvent) -> tuple[float, list[str], str]:
        symbol_set = {symbol.upper() for symbol in event.symbols}
        direct = [
            position
            for position in snapshot.positions
            if position.asset.symbol.upper() in symbol_set
        ]
        if direct:
            exposure = sum(position.weight or 0.0 for position in direct)
            return exposure, [position.asset.symbol for position in direct], "Direct symbol overlap with portfolio holdings."

        if event.category == NewsEventCategory.INDUSTRY:
            sectors = self._matched_sectors(event)
            sector_positions = [
                position
                for position in snapshot.positions
                if position.asset.sector in sectors
            ]
            if sector_positions:
                exposure = sum(position.weight or 0.0 for position in sector_positions)
                return exposure, [position.asset.symbol for position in sector_positions], f"Industry event matched sectors: {', '.join(sorted(sectors))}."

        if event.category == NewsEventCategory.MACRO:
            invested_weight = sum(position.weight or 0.0 for position in snapshot.positions)
            symbols = [position.asset.symbol for position in snapshot.positions]
            return min(1.0, invested_weight), symbols, "Macro event is applied to invested portfolio exposure."

        return 0.0, [], "No direct symbol, sector, or macro exposure match."

    def _matched_sectors(self, event: NewsEvent) -> set[str]:
        text = f"{event.title} {event.summary} {' '.join(event.keywords)}".lower()
        return {
            sector
            for sector, keywords in SECTOR_KEYWORDS.items()
            if any(keyword in text for keyword in keywords)
        }


class NewsLayer:
    def __init__(self, config: AgentConfig):
        self.fetcher = NewsFetcher(config)
        self.classifier = NewsEventClassifier()
        self.impact_analyzer = NewsImpactAnalyzer()

    def build(self, snapshot: PortfolioSnapshot) -> tuple[List[NewsItem], List[NewsEvent], List[NewsImpact], str | None]:
        symbols = [position.asset.symbol for position in snapshot.positions]
        items = self.fetcher.fetch(symbols)
        events = self.classifier.classify(items)
        impacts = self.impact_analyzer.analyze(snapshot, events)
        summary = self._summary(items, events, impacts)
        return items, events, impacts, summary

    def _summary(self, items: List[NewsItem], events: List[NewsEvent], impacts: List[NewsImpact]) -> str | None:
        if not items:
            return None
        top_impacts = sorted(impacts, key=lambda item: item.news_impact, reverse=True)[:3]
        if not top_impacts:
            return f"{len(items)} news item(s) collected; no portfolio-relevant event impact identified."
        parts = [
            f"{impact.theme_key}: impact {impact.news_impact:.1f}/100 on {', '.join(impact.affected_symbols) or 'no direct holding'}"
            for impact in top_impacts
        ]
        return f"{len(items)} news item(s), {len(events)} classified event(s). Top impacts: " + "; ".join(parts)
