"""Bridge → Portal 이벤트 처리."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from portal.services.nr_donation_adapter import NrDonationAdapter
from shared.repos.streamer_repo import StreamerRepo

logger = logging.getLogger(__name__)


class EventService:
    def __init__(self, *, streamer_repo: StreamerRepo, nr_adapter: NrDonationAdapter):
        self._repo = streamer_repo
        self._nr = nr_adapter

    def handle_event(self, body: dict[str, Any]) -> dict[str, Any]:
        streamer_uid = str(body.get("streamerUid") or "").strip()
        event_type = str(body.get("type") or "").strip().lower()
        payload = body.get("payload") or {}

        if not streamer_uid:
            raise HTTPException(400, "streamerUid 필요")
        if not event_type:
            raise HTTPException(400, "type 필요")

        streamer = self._repo.get(streamer_uid)
        if not streamer:
            raise HTTPException(404, "스트리머 없음")

        if event_type == "donation":
            return self._handle_donation(streamer, payload)

        raise HTTPException(400, f"지원하지 않는 type: {event_type}")

    def _handle_donation(self, streamer, payload: dict[str, Any]) -> dict[str, Any]:
        mc_username = streamer.resolve_mc_username()
        donator = str(payload.get("donatorNickname") or "")
        amount = str(payload.get("payAmount") or "")
        text = str(payload.get("donationText") or "")

        if not self._nr.enabled:
            raise HTTPException(503, "NR-Donation 어댑터 비활성")

        try:
            self._nr.send_donation(
                mc_username=mc_username,
                donator_nickname=donator,
                pay_amount=amount,
                donation_text=text,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            logger.exception("NR-Donation 전송 실패 uid=%s", streamer.uid[:8])
            raise HTTPException(502, f"NR-Donation 전송 실패: {exc}") from exc

        return {
            "ok": True,
            "type": "donation",
            "streamer_uid": streamer.uid,
            "mc_username": mc_username,
        }
