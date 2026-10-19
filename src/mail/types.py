"""Provider-neutral email shapes. Message text is only held in memory while an email is analysed."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Direction = Literal["in", "out"]


@dataclass(frozen=True)
class MailItem:
    provider_id: str
    thread_id: str | None
    internet_id: str | None  # RFC 5322 Message-ID
    direction: Direction
    from_address: str | None
    from_name: str | None
    to_addresses: tuple[str, ...]
    subject: str
    text: str  # snippet or plain-text body; never stored in full
    sent_at: datetime
    web_link: str | None = None
    references: tuple[str, ...] = field(default_factory=tuple)  # In-Reply-To and References ids


def domain_of(address: str | None) -> str:
    return address.rsplit("@", 1)[-1].lower() if address and "@" in address else ""
