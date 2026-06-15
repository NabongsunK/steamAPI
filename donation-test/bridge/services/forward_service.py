"""SteamAPI POST /events 전송 (Phase 4)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from shared.models.events import DonationEvent

logger = logging.getLogger(__name__)


def normalize_donation(event: DonationEvent) -> dict[str, Any]:
    return {
        "streamerUid": event.streamer_uid,
        "type": "donation",
        "payload": {
            "donatorNickname": event.donator_nickname,
            "payAmount": event.pay_amount,
            "donationText": event.donation_text,
            "donationType": event.donation_type,
            "channelId": event.channel_id,
            "donatorChannelId": event.donator_channel_id,
        },
    }


class ForwardService:
    def __init__(self, *, api_url: str, api_secret: str, enabled: bool):
        self._api_url = api_url
        self._api_secret = api_secret
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled and bool(self._api_url)

    def on_donation(self, event: DonationEvent) -> None:
        if not self.enabled:
            return
        body = normalize_donation(event)
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_secret:
            headers["Authorization"] = f"Bearer {self._api_secret}"
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(f"{self._api_url}/events", json=body, headers=headers)
                resp.raise_for_status()
            logger.info("[%s] SteamAPI 전송 OK", event.streamer_uid[:8])
        except Exception as exc:
            logger.error("[%s] SteamAPI 전송 실패: %s", event.streamer_uid[:8], exc)
