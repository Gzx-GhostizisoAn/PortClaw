from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from ..config import PROJECT_ROOT, ChannelConfig
from .base import ChannelMessage, ChannelReply


class JsonlChannelAdapter:
    def __init__(self, config: ChannelConfig):
        self.config = config
        self.channel_id = config.channel_id
        self.channel_type = config.channel_type
        self.inbox = self._resolve_path(config.options.get("inbox", "messages/inbox.jsonl"))
        self.outbox = self._resolve_path(config.options.get("outbox", "messages/outbox.jsonl"))
        self.processed = self._resolve_path(config.options.get("processed", "messages/processed.jsonl"))

    def receive(self) -> Iterable[ChannelMessage]:
        self.inbox.parent.mkdir(parents=True, exist_ok=True)
        if not self.inbox.exists():
            return []
        lines = [line for line in self.inbox.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not lines:
            return []

        messages = []
        with self.processed.open("a", encoding="utf-8") as processed_file:
            for line in lines:
                item = json.loads(line)
                message = ChannelMessage(
                    message_id=str(item.get("message_id") or uuid4().hex),
                    channel_id=self.channel_id,
                    channel_type=self.channel_type,
                    sender_id=str(item.get("sender_id") or "local_user"),
                    text=str(item.get("text") or ""),
                    created_at=_parse_time(item.get("created_at")),
                    metadata={k: str(v) for k, v in item.get("metadata", {}).items()},
                )
                messages.append(message)
                processed_file.write(json.dumps(item, ensure_ascii=False) + "\n")
        self.inbox.write_text("", encoding="utf-8")
        return messages

    def send(self, reply: ChannelReply) -> None:
        self.outbox.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "message_id": reply.message_id,
            "channel_id": reply.channel_id,
            "channel_type": reply.channel_type,
            "recipient_id": reply.recipient_id,
            "text": reply.text,
            "audit_id": reply.audit_id,
            "created_at": reply.created_at.isoformat(),
            "metadata": reply.metadata,
        }
        with self.outbox.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else PROJECT_ROOT / path


def _parse_time(value: object) -> datetime:
    if not value:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return datetime.utcnow()
