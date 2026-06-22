"""후원 조회 API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from portal.session_util import get_streamer_uid

router = APIRouter(tags=["donations"])


@router.get("/my/donations")
async def my_donations(
    request: Request,
    limit: int = Query(default=30, ge=1, le=200),
) -> dict[str, Any]:
    """세션에 연결된 스트리머의 후원만 조회 (브라우저 쿠키)."""
    deps = request.app.state.deps
    streamer_uid = get_streamer_uid(request, deps.streamer_repo)
    if not streamer_uid:
        raise HTTPException(401, "연동 세션이 없습니다. 치지직 연결 후 이용하세요.")
    streamer = deps.streamer_repo.get(streamer_uid)
    if not streamer or not streamer.has_token:
        raise HTTPException(403, "치지직 OAuth 연동이 필요합니다.")

    items = deps.donation_repo.sqlite.list_recent(
        limit=limit, offset=0, streamer_uid=streamer_uid
    )
    return {
        "display_name": streamer.display_name,
        "count": len(items),
        "total": deps.donation_repo.sqlite.count(streamer_uid=streamer_uid),
        "donations": items,
    }


@router.get("/donations")
async def donations(
    request: Request,
    streamer_uid: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    deps = request.app.state.deps
    if streamer_uid and not deps.streamer_repo.get(streamer_uid):
        raise HTTPException(404, "스트리머 없음")
    page_limit = limit or deps.settings.shared.donation_list_limit
    items = deps.donation_repo.sqlite.list_recent(
        limit=page_limit, offset=offset, streamer_uid=streamer_uid
    )
    return {
        "source": "sqlite",
        "streamer_uid": streamer_uid,
        "count": len(items),
        "total": deps.donation_repo.sqlite.count(streamer_uid=streamer_uid),
        "queue_pending": deps.donation_repo.queue.queue_length(),
        "donations": items,
    }


@router.get("/donations/recent")
async def donations_recent(
    request: Request,
    streamer_uid: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=200),
) -> dict[str, Any]:
    deps = request.app.state.deps
    page_limit = limit or deps.settings.shared.donation_list_limit
    records = deps.donation_repo.queue.recent(limit=page_limit)
    if streamer_uid:
        records = [r for r in records if r.streamer_uid == streamer_uid]
    items = [
        {
            "streamer_uid": r.streamer_uid,
            "received_at": r.received_at,
            "donator_nickname": r.donator_nickname,
            "pay_amount": r.pay_amount,
            "donation_text": r.donation_text,
            "donation_type": r.donation_type,
            "channel_id": r.channel_id,
            "donator_channel_id": r.donator_channel_id,
        }
        for r in records
    ]
    return {
        "source": "redis",
        "streamer_uid": streamer_uid,
        "count": len(items),
        "queue_pending": deps.donation_repo.queue.queue_length(),
        "donations": items,
    }
