"""스트리머 등록 · 삭제 · auth reset."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from shared.chzzk.api import list_user_sessions_sync, revoke_token_sync
from shared.repos.streamer_repo import Streamer, StreamerRepo

from portal.config import PortalSettings
from portal.services.bridge_client import BridgeClient

logger = logging.getLogger(__name__)


class StreamerService:
    def __init__(
        self,
        *,
        settings: PortalSettings,
        streamer_repo: StreamerRepo,
        bridge_client: BridgeClient,
    ):
        self._settings = settings
        self._repo = streamer_repo
        self._bridge = bridge_client

    def connect_by_display_name(self, display_name: str, mc_username: str = "") -> Streamer:
        name = display_name.strip()
        if not name:
            raise HTTPException(400, "닉네임을 입력하세요.")
        streamer, created = self._repo.get_or_create(name)
        mc = mc_username.strip()
        if mc and mc != streamer.mc_username:
            self._repo.update_mc_username(streamer.uid, mc)
            streamer = self._repo.get(streamer.uid) or streamer
        elif created and not streamer.mc_username:
            self._repo.update_mc_username(streamer.uid, name)
            streamer = self._repo.get(streamer.uid) or streamer
        self._bridge.start_listener(streamer.uid)
        return streamer

    def create(self, display_name: str, *, mc_username: str = "") -> Streamer:
        streamer = self._repo.create(display_name, mc_username=mc_username)
        self._bridge.start_listener(streamer.uid)
        return streamer

    def get(self, uid: str) -> Streamer | None:
        return self._repo.get(uid)

    def list_all(self) -> list[Streamer]:
        return self._repo.list_all()

    def delete(self, uid: str) -> dict[str, Any]:
        streamer = self._repo.get(uid)
        if not streamer:
            raise HTTPException(404, "스트리머 없음")

        revoke = self._revoke_tokens_if_any(uid)
        self._bridge.stop_listener(uid)
        self._repo.delete(uid)

        return {
            "message": f"삭제됨: {streamer.display_name}",
            "streamer_uid": uid,
            **revoke,
        }

    def reset_auth(self, streamer_uid: str) -> dict[str, Any]:
        streamer = self._repo.get(streamer_uid)
        if not streamer:
            raise HTTPException(404, "스트리머 없음")

        self._bridge.stop_listener(streamer_uid)
        revoke = self._revoke_tokens_if_any(streamer_uid)
        self._repo.clear_tokens(streamer_uid)
        self._bridge.start_listener(streamer_uid)

        return {
            "message": f"OAuth 초기화 — /auth/chzzk?uid={streamer_uid} 로 다시 로그인",
            "streamer_uid": streamer_uid,
            **revoke,
        }

    def _revoke_tokens_if_any(self, streamer_uid: str) -> dict[str, Any]:
        tokens = self._repo.get_tokens(streamer_uid)
        shared = self._settings.shared
        revoked = False
        revoke_error: str | None = None
        sessions_before: Any = None

        if tokens and tokens.get("access_token") and shared.chzzk_client_id and shared.chzzk_client_secret:
            try:
                sessions_before = list_user_sessions_sync(tokens["access_token"])
            except Exception as exc:
                logger.warning("세션 목록 조회 실패: %s", exc)
            try:
                revoke_token_sync(shared.chzzk_client_id, shared.chzzk_client_secret, tokens["access_token"])
                revoked = True
            except Exception as exc:
                revoke_error = str(exc)

        return {
            "token_revoked": revoked,
            "revoke_error": revoke_error,
            "sessions_before_reset": sessions_before,
        }

    def bridge_streamer_status(self, streamer_uid: str) -> dict[str, Any] | None:
        status = self._bridge.get_status()
        if not status:
            return None
        for row in status.get("streamers") or []:
            if row.get("streamer_uid") == streamer_uid:
                return row
        return None

    def bridge_statuses(self) -> list[dict[str, Any]]:
        status = self._bridge.get_status()
        if not status:
            return [
                {
                    "streamer_uid": s.uid,
                    "display_name": s.display_name,
                    "chzzk_channel_id": s.chzzk_channel_id,
                    "has_token": s.has_token,
                    "listener_status": "bridge_unreachable",
                    "session_key": None,
                    "last_error": "bridge 연결 실패",
                }
                for s in self._repo.list_all()
            ]
        return status.get("streamers") or []
