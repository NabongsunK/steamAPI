"""NR-Donation 플러그인 WebSocket 어댑터."""

from __future__ import annotations

import logging
import re

from websocket import WebSocketTimeoutException, create_connection

logger = logging.getLogger(__name__)

_FIELD_SEP = "//"


def _sanitize_field(value: str) -> str:
    """NR-Donation 프로토콜 구분자 제거."""
    text = (value or "").strip()
    if not text:
        return "null"
    return re.sub(r"//+", " ", text)


class NrDonationAdapter:
    def __init__(self, *, ws_url: str, enabled: bool = True, timeout_sec: float = 10.0):
        base = ws_url.rstrip("/")
        candidates = [base]
        if not base.endswith("/ws"):
            candidates.append(f"{base}/ws")
        self._ws_urls = candidates
        self._enabled = enabled and bool(ws_url)
        self._timeout_sec = timeout_sec

    @property
    def enabled(self) -> bool:
        return self._enabled

    def send_donation(
        self,
        *,
        mc_username: str,
        donator_nickname: str,
        pay_amount: str,
        donation_text: str,
        platform: str = "chzzk",
    ) -> None:
        if not self.enabled:
            logger.warning("NR-Donation 어댑터 비활성 (NR_DONATION_WS_URL 미설정)")
            return

        mc = mc_username.strip()
        if not mc:
            raise ValueError("mc_username 필요")

        try:
            amount = int(str(pay_amount).strip())
        except ValueError as exc:
            raise ValueError(f"payAmount 정수 아님: {pay_amount!r}") from exc

        sender = _sanitize_field(donator_nickname)
        message = _sanitize_field(donation_text)

        last_error: Exception | None = None
        for url in self._ws_urls:
            try:
                self._send_once(
                    url,
                    mc=mc,
                    platform=platform,
                    sender=sender,
                    amount=amount,
                    message=message,
                )
                logger.info("NR-Donation 전송 OK mc=%s amount=%s url=%s", mc, amount, url)
                return
            except Exception as exc:
                last_error = exc
                logger.warning("NR-Donation WS 실패 url=%s: %s", url, exc)

        raise RuntimeError(f"NR-Donation WS 연결 실패: {last_error}") from last_error

    def _send_once(
        self,
        ws_url: str,
        *,
        mc: str,
        platform: str,
        sender: str,
        amount: int,
        message: str,
    ) -> None:
        ws = create_connection(ws_url, timeout=self._timeout_sec)
        try:
            try:
                hello = ws.recv()
            except WebSocketTimeoutException as exc:
                raise RuntimeError("NR-Donation WS handshake timeout") from exc

            if hello and "getSessionsId" not in hello:
                logger.debug("NR-Donation WS 예상 외 첫 메시지: %s", hello)

            ws.send(f"user{_FIELD_SEP}setSessionsId{_FIELD_SEP}{mc}")
            ws.send(
                f"user{_FIELD_SEP}event{_FIELD_SEP}donation{_FIELD_SEP}"
                f"{platform}{_FIELD_SEP}{sender}{_FIELD_SEP}{amount}{_FIELD_SEP}{message}"
            )
        finally:
            ws.close()
