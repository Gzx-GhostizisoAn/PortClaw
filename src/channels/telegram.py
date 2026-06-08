from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..config import ChannelConfig
from .base import ChannelMessage, ChannelReply


class TelegramChannelAdapter:
    def __init__(self, config: ChannelConfig):
        self.config = config
        self.channel_id = config.channel_id
        self.channel_type = config.channel_type
        self.bot_token = config.credentials.get("bot_token") or config.credentials.get("token") or ""
        self.offset = int(config.options.get("offset", "0") or 0)
        self.timeout = int(config.options.get("timeout", "20") or 20)

    def receive(self) -> Iterable[ChannelMessage]:
        self._require_token()
        payload = self._api_get("getUpdates", {"offset": self.offset, "timeout": self.timeout})
        updates = payload.get("result", []) if isinstance(payload, dict) else []
        messages = []
        for update in updates:
            update_id = int(update.get("update_id", 0))
            self.offset = max(self.offset, update_id + 1)
            raw_message = update.get("message") or update.get("edited_message") or {}
            text = raw_message.get("text") or ""
            chat = raw_message.get("chat") or {}
            if not text or not chat.get("id"):
                continue
            messages.append(
                ChannelMessage(
                    message_id=str(raw_message.get("message_id") or update_id),
                    channel_id=self.channel_id,
                    channel_type=self.channel_type,
                    sender_id=str(chat["id"]),
                    text=str(text),
                    created_at=datetime.utcfromtimestamp(int(raw_message.get("date", 0) or 0))
                    if raw_message.get("date")
                    else datetime.utcnow(),
                    metadata={
                        "telegram_update_id": str(update_id),
                        "chat_id": str(chat["id"]),
                        "chat_type": str(chat.get("type", "")),
                    },
                )
            )
        return messages

    def send(self, reply: ChannelReply) -> None:
        self._require_token()
        self._api_get(
            "sendMessage",
            {
                "chat_id": reply.recipient_id,
                "text": reply.text[:3900],
            },
        )

    def _api_get(self, method: str, params: dict[str, object]) -> dict:
        url = f"https://api.telegram.org/bot{self.bot_token}/{method}?{urlencode(params)}"
        request = Request(url, headers={"User-Agent": "PortClaw/0.1"})
        with urlopen(request, timeout=self.timeout + 10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _require_token(self) -> None:
        if not self.bot_token:
            raise RuntimeError(f"Telegram channel {self.channel_id} requires bot_token")
