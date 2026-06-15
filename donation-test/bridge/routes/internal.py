"""bridge 내부 API (portal 전용)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["internal"])


def _deps(request: Request):
    return request.app.state.deps


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "bridge"}


@router.get("/internal/status")
async def internal_status(request: Request) -> dict[str, Any]:
    deps = _deps(request)
    streamers = deps.ingestion.statuses()
    listening = sum(1 for s in streamers if s["listener_status"] == "listening")
    return {
        "service": "bridge",
        "streamer_count": len(streamers),
        "listening_count": listening,
        "streamers": streamers,
        "storage": deps.donation_repo.stats(),
        "forward_enabled": deps.forward_service.enabled,
    }


@router.post("/internal/listeners/{streamer_uid}/start")
async def start_listener(streamer_uid: str, request: Request) -> dict[str, str]:
    deps = _deps(request)
    if not deps.streamer_repo.get(streamer_uid):
        raise HTTPException(404, "스트리머 없음")
    deps.ingestion.start(streamer_uid)
    return {"message": f"리스너 시작: {streamer_uid}"}


@router.post("/internal/listeners/{streamer_uid}/stop")
async def stop_listener(streamer_uid: str, request: Request) -> dict[str, str]:
    deps = _deps(request)
    deps.ingestion.stop(streamer_uid)
    return {"message": f"리스너 중지: {streamer_uid}"}


@router.post("/internal/listeners/{streamer_uid}/restart")
async def restart_listener(streamer_uid: str, request: Request) -> dict[str, str]:
    deps = _deps(request)
    if not deps.streamer_repo.get(streamer_uid):
        raise HTTPException(404, "스트리머 없음")
    deps.ingestion.restart(streamer_uid)
    return {"message": f"리스너 재시작: {streamer_uid}"}


@router.post("/internal/listeners/restart-all")
async def restart_all_listeners(request: Request) -> dict[str, str]:
    deps = _deps(request)
    deps.ingestion.restart_all()
    deps.donation_repo.stop_worker()
    deps.donation_repo.start_worker()
    return {"message": "모든 리스너 + 큐 워커 재시작"}
