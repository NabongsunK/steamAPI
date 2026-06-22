"""Bridge → Portal 이벤트 수신 (NR-Donation 연동)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

router = APIRouter(tags=["events"])


def _verify_secret(request: Request, authorization: str | None) -> None:
    secret = request.app.state.deps.settings.steam_api_secret
    if not secret:
        raise HTTPException(503, "STEAM_API_SECRET 미설정")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Authorization: Bearer 필요")
    token = authorization.removeprefix("Bearer ").strip()
    if token != secret:
        raise HTTPException(401, "인증 실패")


@router.post("/events")
async def post_event(
    request: Request,
    body: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _verify_secret(request, authorization)
    return request.app.state.deps.event_service.handle_event(body)
