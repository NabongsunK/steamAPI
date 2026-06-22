"""스트리머 admin API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(tags=["streamers"])


class StreamerCreateBody(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    mc_username: str = Field(default="", max_length=100)


class McUsernameBody(BaseModel):
    mc_username: str = Field(min_length=1, max_length=100)


@router.post("/streamers")
async def create_streamer(request: Request, body: StreamerCreateBody) -> dict[str, Any]:
    deps = request.app.state.deps
    streamer = deps.streamer_service.create(body.display_name, mc_username=body.mc_username)
    return {
        "streamer_uid": streamer.uid,
        "display_name": streamer.display_name,
        "mc_username": streamer.resolve_mc_username(),
        "oauth_url": f"/auth/chzzk?uid={streamer.uid}",
        "message": "OAuth URL로 스트리머 본인 계정 로그인",
    }


@router.get("/streamers")
async def list_streamers(request: Request) -> dict[str, Any]:
    deps = request.app.state.deps
    streamers = deps.streamer_service.bridge_statuses()
    return {"count": len(streamers), "streamers": streamers}


@router.get("/streamers/{streamer_uid}")
async def get_streamer(request: Request, streamer_uid: str) -> dict[str, Any]:
    deps = request.app.state.deps
    streamer = deps.streamer_service.get(streamer_uid)
    if not streamer:
        raise HTTPException(404, "스트리머 없음")
    status = deps.streamer_service.bridge_streamer_status(streamer_uid)
    return {
        "streamer_uid": streamer.uid,
        "display_name": streamer.display_name,
        "mc_username": streamer.resolve_mc_username(),
        "chzzk_channel_id": streamer.chzzk_channel_id,
        "has_token": streamer.has_token,
        "listener": status,
        "oauth_url": f"/auth/chzzk?uid={streamer.uid}",
    }


@router.patch("/streamers/{streamer_uid}/mc-username")
async def patch_mc_username(
    request: Request, streamer_uid: str, body: McUsernameBody
) -> dict[str, Any]:
    deps = request.app.state.deps
    if not deps.streamer_service.get(streamer_uid):
        raise HTTPException(404, "스트리머 없음")
    deps.streamer_repo.update_mc_username(streamer_uid, body.mc_username)
    streamer = deps.streamer_service.get(streamer_uid)
    return {
        "streamer_uid": streamer_uid,
        "mc_username": streamer.resolve_mc_username() if streamer else body.mc_username,
    }


@router.delete("/streamers/{streamer_uid}")
async def delete_streamer(request: Request, streamer_uid: str) -> dict[str, Any]:
    return request.app.state.deps.streamer_service.delete(streamer_uid)


@router.post("/streamers/{streamer_uid}/listener/restart")
async def restart_streamer_listener(request: Request, streamer_uid: str) -> dict[str, str]:
    deps = request.app.state.deps
    if not deps.streamer_service.get(streamer_uid):
        raise HTTPException(404, "스트리머 없음")
    deps.bridge_client.restart_listener(streamer_uid)
    return {"message": f"리스너 재시작: {streamer_uid}"}


@router.post("/streamers/{streamer_uid}/auth/reset")
async def reset_streamer_auth(request: Request, streamer_uid: str) -> dict[str, Any]:
    return request.app.state.deps.streamer_service.reset_auth(streamer_uid)
