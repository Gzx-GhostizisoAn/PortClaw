from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, Protocol


@dataclass
class ChannelMessage:
    message_id: str
    channel_id: str
    channel_type: str
    sender_id: str
    text: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class ChannelReply:
    message_id: str
    channel_id: str
    channel_type: str
    recipient_id: str
    text: str
    audit_id: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, str] = field(default_factory=dict)


class ChannelAdapter(Protocol):
    channel_id: str
    channel_type: str

    def receive(self) -> Iterable[ChannelMessage]:
        ...

    def send(self, reply: ChannelReply) -> None:
        ...
