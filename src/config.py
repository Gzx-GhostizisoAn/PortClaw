from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "local_config.json"

SUPPORTED_LLM_PROVIDERS: Dict[str, Dict[str, object]] = {
    "local_template": {
        "label": "Local Template",
        "default_model": "local-template",
        "models": ["local-template"],
        "requires_api_key": False,
        "default_base_url": "",
    },
    "qwen": {
        "label": "Qwen",
        "default_model": "qwen-max",
        "models": ["qwen-max", "qwen-plus", "qwen-turbo", "qwen-long"],
        "requires_api_key": True,
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    "openai": {
        "label": "OpenAI",
        "default_model": "gpt-4o-mini",
        "models": ["gpt-4o", "gpt-4o-mini", "o3", "o4-mini"],
        "requires_api_key": True,
        "default_base_url": "",
    },
    "deepseek": {
        "label": "DeepSeek",
        "default_model": "deepseek-v4-flash",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"],
        "requires_api_key": True,
        "default_base_url": "https://api.deepseek.com",
    },
    "openai_compatible": {
        "label": "OpenAI Compatible",
        "default_model": "custom-model",
        "models": ["custom-model"],
        "requires_api_key": True,
        "default_base_url": "",
    },
}

SUPPORTED_CHANNELS: Dict[str, Dict[str, object]] = {
    "cli": {"label": "CLI", "status": "implemented"},
    "jsonl": {"label": "Local JSONL Message Gateway", "status": "implemented"},
    "telegram": {"label": "Telegram Bot API", "status": "implemented"},
    "discord": {"label": "Discord Bot", "status": "planned"},
    "slack": {"label": "Slack App", "status": "planned"},
    "whatsapp": {"label": "WhatsApp bridge", "status": "planned"},
    "wechat": {"label": "WeChat / WeCom bridge", "status": "planned"},
    "qq": {"label": "QQ bridge", "status": "planned"},
}

SUPPORTED_MARKET_DATA_PROVIDERS: Dict[str, Dict[str, object]] = {
    "demo": {
        "label": "Demo Local Data",
        "category": "local",
        "requires_api_key": False,
        "description": "Local sample portfolio and synthetic metrics for testing.",
    },
    "yahoo": {
        "label": "Yahoo Finance",
        "category": "free",
        "requires_api_key": False,
        "description": "Free public market data via Yahoo Finance/yfinance. Good for quote and history enrichment.",
    },
    "akshare": {
        "label": "AKShare",
        "category": "free",
        "requires_api_key": False,
        "description": "Free public China-market data interfaces, including Eastmoney and other public sources.",
    },
    "eodhd": {
        "label": "EODHD",
        "category": "commercial",
        "requires_api_key": True,
        "description": "Commercial EOD, fundamentals, and news data provider.",
    },
    "twelve_data": {
        "label": "Twelve Data",
        "category": "commercial",
        "requires_api_key": True,
        "description": "Commercial unified market data provider.",
    },
}


class LLMConfig(BaseModel):
    provider: str = "local_template"
    model: str = "local-template"
    api_key: str = ""
    base_url: str = ""


class MarketDataConfig(BaseModel):
    provider: str = "demo"
    api_key: str = ""
    base_url: str = ""
    mode: str = "local"


class StorageConfig(BaseModel):
    audit_dir: str = "audit_runs"
    message_dir: str = "messages"


class RiskPreferences(BaseModel):
    max_single_position_weight: float = 0.25
    high_volatility_20d: float = 0.04
    max_largest_position_weight: float = 0.35


class ChannelConfig(BaseModel):
    channel_id: str
    channel_type: str
    enabled: bool = True
    credentials: Dict[str, str] = Field(default_factory=dict)
    options: Dict[str, str] = Field(default_factory=dict)


class AgentConfig(BaseModel):
    user_id: str = "local_user"
    base_currency: str = "USD"
    llm: LLMConfig = Field(default_factory=LLMConfig)
    channels: List[ChannelConfig] = Field(
        default_factory=lambda: [
            ChannelConfig(channel_id="local_cli", channel_type="cli"),
            ChannelConfig(
                channel_id="local_jsonl",
                channel_type="jsonl",
                options={"inbox": "messages/inbox.jsonl", "outbox": "messages/outbox.jsonl"},
            ),
        ]
    )
    market_data: MarketDataConfig = Field(default_factory=MarketDataConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    risk_preferences: RiskPreferences = Field(default_factory=RiskPreferences)


def config_path() -> Path:
    load_dotenv(PROJECT_ROOT / ".env")
    configured = os.getenv("FINLOCAL_CONFIG")
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else PROJECT_ROOT / path
    return DEFAULT_CONFIG_PATH


def load_config(path: Optional[Path] = None) -> AgentConfig:
    load_dotenv(PROJECT_ROOT / ".env")
    path = path or config_path()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        config = AgentConfig.model_validate(data)
    else:
        config = AgentConfig()

    qwen_key = os.getenv("QWEN_API_KEY", "")
    openai_key = os.getenv("OPENAI_API_KEY", "")
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
    eodhd_key = os.getenv("EODHD_API_KEY", "")
    twelve_key = os.getenv("TWELVE_DATA_API_KEY", "")

    if qwen_key:
        config.llm.provider = "qwen"
        config.llm.model = config.llm.model if config.llm.model != "local-template" else "qwen-max"
        config.llm.api_key = qwen_key
        config.llm.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    elif openai_key:
        config.llm.provider = "openai"
        config.llm.model = config.llm.model if config.llm.model != "local-template" else "gpt-4o-mini"
        config.llm.api_key = openai_key
    elif deepseek_key:
        config.llm.provider = "deepseek"
        config.llm.model = config.llm.model if config.llm.model != "local-template" else "deepseek-v4-flash"
        config.llm.api_key = deepseek_key
        config.llm.base_url = "https://api.deepseek.com"

    config.llm = normalize_llm_config(config.llm)

    if eodhd_key:
        config.market_data.provider = "eodhd"
        config.market_data.api_key = eodhd_key
    elif twelve_key:
        config.market_data.provider = "twelve_data"
        config.market_data.api_key = twelve_key

    config.market_data = normalize_market_data_config(config.market_data)
    return config


def normalize_llm_config(config: LLMConfig) -> LLMConfig:
    provider_meta = SUPPORTED_LLM_PROVIDERS.get(config.provider)
    if not provider_meta:
        return config
    if not provider_meta["requires_api_key"]:
        config.api_key = ""
        config.base_url = str(provider_meta.get("default_base_url", ""))
    if not config.model:
        config.model = str(provider_meta["default_model"])
    if not config.base_url:
        config.base_url = str(provider_meta.get("default_base_url", ""))
    return config


def available_llm_models() -> Dict[str, Dict[str, object]]:
    return SUPPORTED_LLM_PROVIDERS


def available_channels() -> Dict[str, Dict[str, object]]:
    return SUPPORTED_CHANNELS


def available_market_data_providers() -> Dict[str, Dict[str, object]]:
    return SUPPORTED_MARKET_DATA_PROVIDERS


def normalize_market_data_config(config: MarketDataConfig) -> MarketDataConfig:
    provider_meta = SUPPORTED_MARKET_DATA_PROVIDERS.get(config.provider)
    if not provider_meta:
        return config
    config.mode = str(provider_meta.get("category", "custom"))
    if not provider_meta["requires_api_key"]:
        config.api_key = ""
        config.base_url = ""
    return config


def save_config(config: AgentConfig, path: Optional[Path] = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
