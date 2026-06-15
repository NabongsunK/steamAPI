"""도메인 이벤트 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DonationEvent:
    streamer_uid: str
    received_at: str
    donator_nickname: str
    pay_amount: str
    donation_text: str
    donation_type: str
    channel_id: str
    donator_channel_id: str
    raw: dict[str, Any] = field(repr=False)
