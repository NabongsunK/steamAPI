"""Socket.IO로 치지직 후원(DONATION) 이벤트 수신."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import socketio

from chzzk_api import (
    ChzzkApiError,
    get_session_url_sync,
    list_user_sessions_sync,
    subscribe_donation_sync,
)
from chzzk_ws import build_engineio_ws_url, normalize_payload, probe_raw_websocket
from donation_store import DonationStore, donation_record_now

logger = logging.getLogger(__name__)


@dataclass
class DonationEvent:
    received_at: str
    donator_nickname: str
    pay_amount: str
    donation_text: str
    donation_type: str
    channel_id: str
    donator_channel_id: str
    raw: dict[str, Any] = field(repr=False)


class DonationListener:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        get_tokens: Callable[[], dict[str, Any] | None],
        save_tokens: Callable[[dict[str, Any]], None],
        refresh_tokens: Callable[[str, str, str], Any],
        store: DonationStore | None = None,
        on_donation: Callable[[DonationEvent], None] | None = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.get_tokens = get_tokens
        self.save_tokens = save_tokens
        self.refresh_tokens = refresh_tokens
        self.store = store
        self.on_donation = on_donation
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._status = "idle"
        self._session_key: str | None = None
        self._last_error: str | None = None

    @property
    def status(self) -> str:
        return self._status

    @property
    def session_key(self) -> str | None:
        return self._session_key

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="donation-listener", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(lambda: None)

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._listen_loop())
        except Exception as exc:
            self._last_error = str(exc)
            self._status = "error"
            logger.exception("후원 리스너 종료: %s", exc)
        finally:
            self._loop.close()

    async def _listen_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._connect_once()
            except ChzzkApiError as exc:
                self._last_error = str(exc)
                self._status = "error"
                logger.error("치지직 API 오류: %s", exc)
                await asyncio.sleep(10)
            except Exception as exc:
                self._last_error = str(exc)
                self._status = "error"
                logger.exception("연결 오류, 30초 후 재시도: %s", exc)
                await asyncio.sleep(30)

    async def _connect_once(self) -> None:
        tokens = self.get_tokens()
        if not tokens or not tokens.get("access_token"):
            self._status = "waiting_for_oauth"
            await asyncio.sleep(2)
            return

        access_token = tokens["access_token"]
        self._status = "connecting"
        await asyncio.to_thread(self._run_socket_session, access_token)

    def _run_socket_session(self, access_token: str) -> None:
        """Socket.IO 세션 — URL 발급 직후 바로 연결 (URL 만료 방지)."""
        active = self._count_active_sessions(access_token)
        if active >= 3:
            raise RuntimeError(
                f"활성 WebSocket 세션이 {active}개(최대 3) — server 중지 후 1~2분 대기"
            )

        try:
            session_url = get_session_url_sync(access_token)
        except ChzzkApiError as exc:
            if "INVALID_TOKEN" not in str(exc) and exc.status_code != 401:
                raise
            raise

        session_ready = threading.Event()
        subscribed = threading.Event()
        connect_error: list[str] = []

        sio = socketio.Client(reconnection=False, logger=False, engineio_logger=False)

        @sio.on("connect")
        def on_connect() -> None:
            logger.info(
                "Socket.IO connect (sid=%s, transport=%s)",
                getattr(sio, "sid", "?"),
                getattr(sio, "transport", "?"),
            )

        @sio.on("connect_error")
        def on_connect_error(data: Any) -> None:
            msg = str(data)
            connect_error.append(msg)
            logger.error("Socket.IO connect_error: %s", msg)

        @sio.on("disconnect")
        def on_disconnect() -> None:
            logger.warning("Socket.IO 연결 끊김")
            self._status = "disconnected"

        @sio.on("SYSTEM")
        def on_system(data: Any) -> None:
            payload = normalize_payload(data)
            logger.info("SYSTEM: %s", json.dumps(payload, ensure_ascii=False))
            msg_type = payload.get("type")
            if msg_type == "connected":
                session_key = (payload.get("data") or {}).get("sessionKey")
                if not session_key:
                    return
                self._session_key = session_key
                session_ready.set()
                try:
                    subscribe_donation_sync(access_token, session_key)
                    logger.info("후원 구독 요청 완료 (sessionKey=%s...)", session_key[:8])
                except ChzzkApiError as exc:
                    connect_error.append(str(exc))
                    logger.error("후원 구독 API 실패: %s", exc)
            elif msg_type == "subscribed":
                event_type = (payload.get("data") or {}).get("eventType")
                if event_type == "DONATION":
                    self._status = "listening"
                    subscribed.set()
            elif msg_type == "revoked":
                self._status = "revoked"
                logger.error("후원 권한이 회수되었습니다: %s", payload)

        @sio.on("DONATION")
        def on_donation(data: Any) -> None:
            payload = normalize_payload(data)
            event = DonationEvent(
                received_at=datetime.now(timezone.utc).isoformat(),
                donator_nickname=str(payload.get("donatorNickname", "")),
                pay_amount=str(payload.get("payAmount", "")),
                donation_text=str(payload.get("donationText", "")),
                donation_type=str(payload.get("donationType", "")),
                channel_id=str(payload.get("channelId", "")),
                donator_channel_id=str(payload.get("donatorChannelId", "")),
                raw=payload,
            )
            logger.info(
                "후원 수신: %s / %s원 / %s",
                event.donator_nickname,
                event.pay_amount,
                event.donation_text,
            )
            if self.store:
                self.store.enqueue(donation_record_now(payload))
            if self.on_donation:
                self.on_donation(event)

        logger.info("Session WS 연결 시도: %s...", session_url[:60])
        logger.debug("Engine.IO URL: %s", build_engineio_ws_url(session_url)[:120])
        try:
            sio.connect(session_url, transports=["websocket"])
        except Exception as exc:
            raw_ok, raw_err, _ = probe_raw_websocket(session_url)
            detail = exc.__cause__ or exc
            hint = raw_err if not raw_ok else str(detail)
            raise RuntimeError(
                f"Socket.IO connect 실패: {exc} — {hint} "
                "(ssio*.nchat.naver.com:443·세션 3개 초과·URL 만료 확인)"
            ) from exc

        if connect_error:
            raise RuntimeError(connect_error[0])

        if not sio.connected:
            raise TimeoutError("Socket.IO 연결 실패 (sio.connected=False)")

        if not session_ready.wait(timeout=20):
            raise TimeoutError(
                "SYSTEM connected 타임아웃 — 세션 URL 만료 또는 WebSocket 프로토콜 불일치"
            )

        if not subscribed.wait(timeout=30):
            raise TimeoutError("후원 구독(subscribed) 타임아웃 — Scope '후원 조회' 확인")

        self._status = "listening"
        self._last_error = None

        while not self._stop.is_set() and sio.connected:
            self._stop.wait(timeout=1)

        if sio.connected:
            sio.disconnect()

    async def _refresh_access_token(self, tokens: dict[str, Any]) -> str:
        if not tokens.get("refresh_token"):
            raise ChzzkApiError("토큰 만료 — /auth/chzzk 로 다시 로그인하세요.")

        refreshed = await self.refresh_tokens(
            self.client_id,
            self.client_secret,
            tokens["refresh_token"],
        )
        tokens.update(
            {
                "access_token": refreshed["accessToken"],
                "refresh_token": refreshed["refreshToken"],
                "token_type": refreshed.get("tokenType", "Bearer"),
                "expires_in": int(refreshed.get("expiresIn", 86400)),
            }
        )
        self.save_tokens(tokens)
        return tokens["access_token"]

    @staticmethod
    def _count_active_sessions(access_token: str) -> int:
        try:
            payload = list_user_sessions_sync(access_token, size=20)
            rows = (payload or {}).get("data") or []
            return sum(1 for row in rows if not row.get("disconnectedDate"))
        except ChzzkApiError as exc:
            logger.warning("세션 목록 조회 실패: %s", exc)
            return 0
