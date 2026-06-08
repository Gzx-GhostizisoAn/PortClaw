from __future__ import annotations

import argparse
import json

from ..config import (
    PROJECT_ROOT,
    AgentConfig,
    ChannelConfig,
    available_channels,
    available_llm_models,
    available_market_data_providers,
    load_config,
    normalize_llm_config,
    normalize_market_data_config,
    save_config,
)
from .common import prompt_text


def choose_from_list(title: str, options: list[str], current: str | None = None) -> str:
    print(f"\n{title}")
    for index, option in enumerate(options, start=1):
        marker = " current" if option == current else ""
        print(f"{index}. {option}{marker}")
    while True:
        raw = input("Choose number, or press Enter to keep current: ").strip()
        if not raw and current in options:
            return current
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        print("Invalid selection.")


def ensure_channel(config: AgentConfig, channel_id: str, channel_type: str, enabled: bool = True) -> ChannelConfig:
    existing = next((item for item in config.channels if item.channel_id == channel_id), None)
    if existing:
        existing.enabled = enabled
        existing.channel_type = channel_type
        return existing
    channel = ChannelConfig(channel_id=channel_id, channel_type=channel_type, enabled=enabled)
    config.channels.append(channel)
    return channel


def cmd_init(_: argparse.Namespace) -> None:
    config_path = PROJECT_ROOT / "config" / "local_config.json"
    env_path = PROJECT_ROOT / ".env"
    if not config_path.exists():
        save_config(AgentConfig(), config_path)
        print(f"Created {config_path}")
    else:
        print(f"Exists {config_path}")
    if not env_path.exists():
        example = PROJECT_ROOT / ".env.example"
        env_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"Created {env_path}")
    else:
        print(f"Exists {env_path}")


def cmd_setup(_: argparse.Namespace) -> None:
    config = load_config()

    print("PortClaw setup")
    print("This wizard configures three things:")
    print("1. Model: the LLM provider/model used after analytics are complete.")
    print("2. Market data: the provider used by data adapters. Demo mode uses local sample data.")
    print("3. Channels: where the agent receives messages, such as CLI or local JSONL gateway.")

    llm_providers = list(available_llm_models().keys())
    config.llm.provider = choose_from_list("LLM provider - who runs the language model", llm_providers, config.llm.provider)
    provider_meta = available_llm_models()[config.llm.provider]
    model_options = [str(item) for item in provider_meta["models"]]
    if config.llm.model not in model_options and config.llm.provider == "openai_compatible":
        model_options = [config.llm.model or str(provider_meta["default_model"])]
    config.llm.model = choose_from_list(
        "LLM model - which model name to call",
        model_options,
        config.llm.model or str(provider_meta["default_model"]),
    )
    if config.llm.provider == "openai_compatible":
        config.llm.model = prompt_text("Custom model name", config.llm.model)
    if provider_meta["requires_api_key"]:
        config.llm.api_key = prompt_text("LLM API key - paste the key from your model provider", config.llm.api_key, secret=True)
    else:
        config.llm.api_key = ""
    default_base_url = str(provider_meta.get("default_base_url", ""))
    config.llm.base_url = prompt_text("LLM base URL - keep default unless using a custom endpoint", config.llm.base_url or default_base_url)
    config.llm = normalize_llm_config(config.llm)

    market_providers = list(available_market_data_providers().keys())
    config.market_data.provider = choose_from_list("Market data provider - where price/news data comes from", market_providers, config.market_data.provider)
    market_meta = available_market_data_providers()[config.market_data.provider]
    if market_meta["requires_api_key"]:
        config.market_data.api_key = prompt_text("Market data API key - paste provider key if required", config.market_data.api_key, secret=True)
    else:
        config.market_data.api_key = ""
    config.market_data.base_url = prompt_text("Market data base URL - usually empty", config.market_data.base_url)
    config.market_data = normalize_market_data_config(config.market_data)

    print("\nChannels")
    use_cli = input("Enable CLI chat? [Y/n]: ").strip().lower() != "n"
    use_jsonl = input("Enable local JSONL message gateway? [Y/n]: ").strip().lower() != "n"
    ensure_channel(config, "local_cli", "cli", use_cli)
    jsonl = ensure_channel(config, "local_jsonl", "jsonl", use_jsonl)
    jsonl.options.setdefault("inbox", "messages/inbox.jsonl")
    jsonl.options.setdefault("outbox", "messages/outbox.jsonl")

    add_external = input("Add an external channel config now? [y/N]: ").strip().lower() == "y"
    if add_external:
        channel_types = [key for key in available_channels().keys() if key not in {"cli", "jsonl"}]
        channel_type = choose_from_list("External channel type", channel_types)
        channel_id = prompt_text("Channel id", f"{channel_type}_personal")
        channel = ensure_channel(config, channel_id, channel_type, True)
        token = prompt_text("Primary channel token/key", channel.credentials.get("token", ""), secret=True)
        if token:
            channel.credentials["token"] = token

    path = save_config(config)
    print(f"\nSaved config: {path}")
    print("Run `python agent.py status` to verify the local agent runtime.")


def cmd_configure(args: argparse.Namespace) -> None:
    config = load_config()
    if args.llm_provider:
        config.llm.provider = args.llm_provider
    if args.llm_model:
        config.llm.model = args.llm_model
    if args.llm_api_key:
        config.llm.api_key = args.llm_api_key
    if args.llm_base_url:
        config.llm.base_url = args.llm_base_url
    config.llm = normalize_llm_config(config.llm)
    if args.market_provider:
        config.market_data.provider = args.market_provider
    if args.market_api_key:
        config.market_data.api_key = args.market_api_key
    if args.market_base_url:
        config.market_data.base_url = args.market_base_url
    config.market_data = normalize_market_data_config(config.market_data)
    path = save_config(config)
    print(f"Saved config: {path}")


def cmd_config_show(_: argparse.Namespace) -> None:
    config = load_config()
    safe = config.model_dump(mode="json")
    if safe.get("llm", {}).get("api_key"):
        safe["llm"]["api_key"] = "***"
    if safe.get("market_data", {}).get("api_key"):
        safe["market_data"]["api_key"] = "***"
    for channel in safe.get("channels", []):
        for key in list(channel.get("credentials", {}).keys()):
            channel["credentials"][key] = "***"
    print(json.dumps(safe, ensure_ascii=False, indent=2))


def cmd_models(_: argparse.Namespace) -> None:
    for provider, meta in available_llm_models().items():
        models = ", ".join(str(item) for item in meta["models"])
        key_note = "requires API key" if meta["requires_api_key"] else "no API key"
        print(f"{provider}: {models} ({key_note})")


def cmd_data_sources(_: argparse.Namespace) -> None:
    for provider, meta in available_market_data_providers().items():
        key_note = "requires API key" if meta["requires_api_key"] else "no API key"
        print(f"{provider}: {meta['label']} [{meta['category']}] ({key_note})")
        print(f"  {meta['description']}")


def register_configuration_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    init_parser = subparsers.add_parser("init", help="create local config files")
    init_parser.set_defaults(func=cmd_init)

    setup_parser = subparsers.add_parser("setup", help="interactive local setup wizard")
    setup_parser.set_defaults(func=cmd_setup)

    config_show_parser = subparsers.add_parser("config-show", help="show current config with secrets masked")
    config_show_parser.set_defaults(func=cmd_config_show)

    models_parser = subparsers.add_parser("models", help="list supported LLM providers and models")
    models_parser.set_defaults(func=cmd_models)

    data_sources_parser = subparsers.add_parser("data-sources", help="list supported market data providers")
    data_sources_parser.set_defaults(func=cmd_data_sources)

    configure_parser = subparsers.add_parser("configure", help="write local API-key config")
    configure_parser.add_argument("--llm-provider", choices=["local_template", "qwen", "openai", "deepseek", "openai_compatible"])
    configure_parser.add_argument("--llm-model")
    configure_parser.add_argument("--llm-api-key")
    configure_parser.add_argument("--llm-base-url")
    configure_parser.add_argument("--market-provider", choices=list(available_market_data_providers().keys()))
    configure_parser.add_argument("--market-api-key")
    configure_parser.add_argument("--market-base-url")
    configure_parser.set_defaults(func=cmd_configure)
