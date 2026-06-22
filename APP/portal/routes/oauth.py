"""OAuth 라우트."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

router = APIRouter(tags=["oauth"])


@router.get("/auth/chzzk")
async def auth_chzzk(request: Request, uid: str = Query(..., description="스트리머 uid")):
    return request.app.state.deps.oauth_service.begin_oauth(uid)


@router.get("/auth/chzzk/callback")
async def auth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    return await request.app.state.deps.oauth_service.handle_callback(request, code, state, error)
