"""OAuth state · 토큰 교환."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, Request
from fastapi.responses import RedirectResponse

from shared.chzzk.api import ChzzkApiError, build_auth_url, exchange_code, new_oauth_state
from shared.repos.streamer_repo import StreamerRepo

from portal.config import PortalSettings
from portal.session_util import set_streamer_uid
from portal.services.bridge_client import BridgeClient

logger = logging.getLogger(__name__)


class OAuthService:
    def __init__(
        self,
        *,
        settings: PortalSettings,
        streamer_repo: StreamerRepo,
        bridge_client: BridgeClient,
    ):
        self._settings = settings
        self._streamer_repo = streamer_repo
        self._bridge = bridge_client
        self._state_file = Path(settings.oauth_state_file)
        self._ttl = settings.oauth_state_ttl_sec

    def register_state(self, state: str, streamer_uid: str) -> None:
        states = self._prune(self._load())
        states[state] = {"created_at": time.time(), "streamer_uid": streamer_uid}
        self._save(states)

    def consume_state(self, state: str) -> str | None:
        states = self._prune(self._load())
        meta = states.pop(state, None)
        self._save(states)
        if not meta:
            return None
        uid = str(meta.get("streamer_uid", "")).strip()
        return uid or None

    def begin_oauth(self, streamer_uid: str) -> RedirectResponse:
        shared = self._settings.shared
        if not shared.chzzk_client_id or not shared.chzzk_client_secret:
            raise HTTPException(500, "CHZZK_CLIENT_ID / CHZZK_CLIENT_SECRET 을 .env 에 설정하세요.")
        if not self._streamer_repo.get(streamer_uid):
            raise HTTPException(404, f"스트리머 없음: {streamer_uid}")

        state = new_oauth_state()
        self.register_state(state, streamer_uid)
        url = build_auth_url(shared.chzzk_client_id, self._settings.redirect_uri, state)
        logger.info("OAuth 시작 uid=%s", streamer_uid[:8])
        return RedirectResponse(url)

    async def handle_callback(
        self,
        request: Request,
        code: str | None,
        state: str | None,
        error: str | None,
    ) -> RedirectResponse:
        if error:
            logger.error("OAuth provider error: %s", error)
            raise HTTPException(400, f"OAuth 실패: {error}")
        if not code or not state:
            raise HTTPException(400, "code 또는 state 가 없습니다.")

        streamer_uid = self.consume_state(state)
        if not streamer_uid:
            raise HTTPException(400, "state 불일치 — /auth/chzzk?uid=... 부터 다시 시작하세요.")
        if not self._streamer_repo.get(streamer_uid):
            raise HTTPException(400, f"스트리머 없음: {streamer_uid}")

        shared = self._settings.shared
        try:
            token_data = await exchange_code(
                shared.chzzk_client_id,
                shared.chzzk_client_secret,
                code,
                state,
            )
        except ChzzkApiError as exc:
            raise HTTPException(400, f"토큰 발급 실패: {exc}") from exc

        self._streamer_repo.save_tokens(
            streamer_uid,
            {
                "access_token": token_data["accessToken"],
                "refresh_token": token_data["refreshToken"],
                "token_type": token_data.get("tokenType", "Bearer"),
                "expires_in": int(token_data.get("expiresIn", 86400)),
            },
        )
        logger.info("OAuth 완료 uid=%s — bridge 리스너 시작 요청", streamer_uid[:8])
        self._bridge.start_listener(streamer_uid)
        set_streamer_uid(request, streamer_uid)
        return RedirectResponse("/?oauth=ok")

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._state_file.exists():
            return {}
        try:
            raw = json.loads(self._state_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if isinstance(raw, dict) and raw and all(isinstance(v, (int, float)) for v in raw.values()):
            return {k: {"created_at": float(v), "streamer_uid": ""} for k, v in raw.items()}
        if not isinstance(raw, dict):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for state, meta in raw.items():
            if isinstance(meta, dict):
                result[state] = {
                    "created_at": float(meta.get("created_at", 0)),
                    "streamer_uid": str(meta.get("streamer_uid", "")),
                }
            elif isinstance(meta, (int, float)):
                result[state] = {"created_at": float(meta), "streamer_uid": ""}
        return result

    def _save(self, states: dict[str, dict[str, Any]]) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(json.dumps(states, ensure_ascii=False, indent=2), encoding="utf-8")

    def _prune(self, states: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        now = time.time()
        return {
            k: v
            for k, v in states.items()
            if now - float(v.get("created_at", 0)) <= self._ttl
        }
