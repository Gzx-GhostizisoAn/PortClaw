from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*_: object, **__: object) -> bool:
        return False


PROJECT_ROOT = Path(os.getenv("PORTCLAW_HOME", Path(__file__).resolve().parents[1])).resolve()
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
        "auth_type": "none",
        "env_vars": [],
        "status": "implemented",
        "description": "Local sample portfolio and synthetic metrics for testing.",
    },
    "yahoo": {
        "label": "Yahoo Finance",
        "category": "free",
        "requires_api_key": False,
        "auth_type": "none",
        "env_vars": [],
        "status": "implemented",
        "description": "Free public market data via Yahoo Finance/yfinance. Good for quote and history enrichment.",
    },
    "akshare": {
        "label": "AKShare",
        "category": "free",
        "requires_api_key": False,
        "auth_type": "none",
        "env_vars": [],
        "status": "planned",
        "description": "Free public China-market data interfaces, including Eastmoney and other public sources.",
    },
    "efinance": {
        "label": "efinance",
        "category": "free",
        "requires_api_key": False,
        "auth_type": "none",
        "env_vars": [],
        "status": "planned",
        "description": "Free open-source Python library for China-market stocks, funds, futures, and public quote data.",
    },
    "ccxt": {
        "label": "CCXT",
        "category": "free_public",
        "requires_api_key": False,
        "auth_type": "none_for_public_market_data",
        "env_vars": ["CCXT_EXCHANGE", "CCXT_API_KEY", "CCXT_SECRET"],
        "status": "planned",
        "description": "Crypto exchange data through CCXT. Public market data usually needs no key; private account/trading APIs need exchange-specific credentials.",
    },
    "fred": {
        "label": "FRED",
        "category": "macro",
        "requires_api_key": True,
        "auth_type": "api_key",
        "env_vars": ["FRED_API_KEY"],
        "status": "planned",
        "description": "Federal Reserve Economic Data macro series. Requires a FRED API key for web service requests.",
    },
    "fmp": {
        "label": "Financial Modeling Prep",
        "category": "commercial",
        "requires_api_key": True,
        "auth_type": "api_key",
        "env_vars": ["FMP_API_KEY"],
        "status": "planned",
        "description": "Financial Modeling Prep API for prices, fundamentals, ratios, calendars, and market data. Requires an API key.",
    },
    "tushare": {
        "label": "Tushare",
        "category": "freemium",
        "requires_api_key": True,
        "auth_type": "token",
        "env_vars": ["TUSHARE_TOKEN"],
        "status": "implemented",
        "description": "Tushare Pro China-market daily history. Requires a Tushare token and may gate endpoints by points or subscription level.",
    },
    "alpha_vantage": {
        "label": "Alpha Vantage",
        "category": "freemium",
        "requires_api_key": True,
        "auth_type": "api_key",
        "env_vars": ["ALPHA_VANTAGE_API_KEY"],
        "status": "planned",
        "description": "Alpha Vantage market, fundamental, FX, crypto, and macro endpoints. Requires an API key; free keys have limits.",
    },
    "rqdata": {
        "label": "RQData",
        "category": "commercial",
        "requires_api_key": True,
        "auth_type": "account_or_license",
        "env_vars": ["RQDATA_USERNAME", "RQDATA_PASSWORD"],
        "status": "planned",
        "description": "Ricequant/RQData China-market data. Requires account or license credentials, commonly username plus password/license key.",
    },
    "eodhd": {
        "label": "EODHD",
        "category": "commercial",
        "requires_api_key": True,
        "auth_type": "api_key",
        "env_vars": ["EODHD_API_KEY"],
        "status": "planned",
        "description": "Commercial EOD, fundamentals, and news data provider.",
    },
    "twelve_data": {
        "label": "Twelve Data",
        "category": "commercial",
        "requires_api_key": True,
        "auth_type": "api_key",
        "env_vars": ["TWELVE_DATA_API_KEY"],
        "status": "planned",
        "description": "Commercial unified market data provider.",
    },
}

MARKET_DATA_ENV_KEYS: tuple[tuple[str, str], ...] = (
    ("eodhd", "EODHD_API_KEY"),
    ("twelve_data", "TWELVE_DATA_API_KEY"),
    ("fred", "FRED_API_KEY"),
    ("fmp", "FMP_API_KEY"),
    ("tushare", "TUSHARE_TOKEN"),
    ("alpha_vantage", "ALPHA_VANTAGE_API_KEY"),
)


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


class NewsConfig(BaseModel):
    provider: str = "auto"
    lookback: str = "7d"


class AppUIConfig(BaseModel):
    language: str = "zh-CN"
    onboarding_completed: bool = False
    cache_policy: str = "standard"
    timezone: str = "Asia/Shanghai"


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
    news: NewsConfig = Field(default_factory=NewsConfig)
    app: AppUIConfig = Field(default_factory=AppUIConfig)
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

    for provider, env_var in MARKET_DATA_ENV_KEYS:
        value = os.getenv(env_var, "")
        if value:
            config.market_data.provider = provider
            config.market_data.api_key = value
            break
    else:
        rqdata_username = os.getenv("RQDATA_USERNAME", "")
        rqdata_password = os.getenv("RQDATA_PASSWORD", "")
        if rqdata_username and rqdata_password:
            config.market_data.provider = "rqdata"
            config.market_data.api_key = f"{rqdata_username}:{rqdata_password}"

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
