"""bridge 내부 API 클라이언트."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class BridgeClient:
    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip("/")

    def get_status(self) -> dict[str, Any] | None:
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self._base_url}/internal/status")
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.warning("bridge status 실패: %s", exc)
            return None

    def start_listener(self, streamer_uid: str) -> None:
        self._post(f"/internal/listeners/{streamer_uid}/start")

    def stop_listener(self, streamer_uid: str) -> None:
        self._post(f"/internal/listeners/{streamer_uid}/stop")

    def restart_listener(self, streamer_uid: str) -> None:
        self._post(f"/internal/listeners/{streamer_uid}/restart")

    def restart_all_listeners(self) -> None:
        self._post("/internal/listeners/restart-all")

    def _post(self, path: str) -> dict[str, Any] | None:
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(f"{self._base_url}{path}")
                resp.raise_for_status()
                return resp.json() if resp.content else {"message": "ok"}
        except Exception as exc:
            logger.warning("bridge POST %s 실패: %s", path, exc)
            return None
