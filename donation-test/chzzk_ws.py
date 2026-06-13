"""치지직 Session WebSocket 연결·진단 유틸."""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse

import certifi
import socketio

logger = logging.getLogger(__name__)


def ssl_ca_bundle() -> str:
    """macOS python.org 빌드 등에서 시스템 CA가 비어 있을 때 certifi 사용."""
    return certifi.where()


def websocket_sslopt() -> dict[str, str]:
    return {"ca_certs": ssl_ca_bundle()}


@dataclass
class WsProbeResult:
    host: str
    port: int
    dns_ok: bool
    tcp_ok: bool
    raw_ws_ok: bool
    socketio_ok: bool
    active_sessions: int | None = None
    errors: list[str] = field(default_factory=list)
    raw_first_packet: str | None = None
    system_payload: Any | None = None

    @property
    def ok(self) -> bool:
        return self.socketio_ok


def parse_session_url(session_url: str) -> tuple[str, int, str]:
    parsed = urlparse(session_url)
    host = parsed.hostname or ""
    port = parsed.port or 443
    auth = parse_qs(parsed.query).get("auth", [""])[0]
    if not host or not auth:
        raise ValueError(f"session URL 형식 오류: {session_url[:80]}...")
    return host, port, auth


def build_engineio_ws_url(session_url: str) -> str:
    host, port, auth = parse_session_url(session_url)
    query = urlencode({"auth": auth, "transport": "websocket", "EIO": "3"})
    return f"wss://{host}:{port}/socket.io/?{query}"


def probe_dns(host: str) -> tuple[bool, str | None]:
    try:
        socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        return True, None
    except OSError as exc:
        return False, str(exc)


def probe_tcp(host: str, port: int = 443, timeout: float = 5.0) -> tuple[bool, str | None]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return True, None
    except OSError as exc:
        return False, str(exc)


def probe_raw_websocket(
    session_url: str,
    *,
    timeout: float = 10.0,
) -> tuple[bool, str | None, str | None]:
    """Engine.IO v3 WebSocket 핸드셰이크만 직접 시도."""
    try:
        import websocket  # websocket-client
    except ImportError:
        return False, "websocket-client 미설치", None

    ws_url = build_engineio_ws_url(session_url)
    try:
        ws = websocket.create_connection(
            ws_url,
            timeout=timeout,
            sslopt=websocket_sslopt(),
        )
        first = ws.recv()
        ws.close()
        preview = first if isinstance(first, str) else first.decode("utf-8", errors="replace")
        return True, None, preview[:200]
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}", None


def connect_socketio(
    session_url: str,
    *,
    on_system: Callable[[dict[str, Any]], None] | None = None,
    on_donation: Callable[[dict[str, Any]], None] | None = None,
    logger_enabled: bool = False,
    wait_system_seconds: float = 20.0,
) -> tuple[socketio.Client, threading.Event, list[str]]:
    """Socket.IO 연결. (sio, system_ready_event, errors) 반환."""
    session_ready = threading.Event()
    errors: list[str] = []

    sio = socketio.Client(
        reconnection=False,
        logger=logger_enabled,
        engineio_logger=logger_enabled,
        ssl_verify=ssl_ca_bundle(),
    )

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
        errors.append(msg)
        logger.error("Socket.IO connect_error: %s", msg)

    @sio.on("SYSTEM")
    def on_system_event(data: Any) -> None:
        payload = normalize_payload(data)
        logger.info("SYSTEM: %s", json.dumps(payload, ensure_ascii=False))
        if on_system:
            on_system(payload)
        if payload.get("type") == "connected":
            session_ready.set()

    if on_donation:

        @sio.on("DONATION")
        def on_donation_event(data: Any) -> None:
            on_donation(normalize_payload(data))

    logger.info("Session WS 연결 시도: %s...", session_url[:60])
    sio.connect(session_url, transports=["websocket"])

    if errors:
        raise RuntimeError(errors[0])
    if not sio.connected:
        raise TimeoutError("Socket.IO 연결 실패 (sio.connected=False)")
    if not session_ready.wait(timeout=wait_system_seconds):
        sio.disconnect()
        raise TimeoutError("SYSTEM connected 타임아웃 — URL 만료 또는 WS 프로토콜 불일치")

    return sio, session_ready, errors


def probe_session_connection(
    session_url: str,
    *,
    active_sessions: int | None = None,
    socketio_logger: bool = False,
    fetch_fresh_url: Callable[[], str] | None = None,
) -> WsProbeResult:
    """세션 URL 진단.

    raw WS와 Socket.IO는 auth 토큰이 1회용이라 **서로 다른 URL**이 필요합니다.
    `fetch_fresh_url`로 Socket.IO 직전에 새 URL을 발급받으세요.
    """
    host, port, _ = parse_session_url(session_url)
    result = WsProbeResult(
        host=host,
        port=port,
        dns_ok=False,
        tcp_ok=False,
        raw_ws_ok=False,
        socketio_ok=False,
        active_sessions=active_sessions,
    )

    dns_ok, dns_err = probe_dns(host)
    result.dns_ok = dns_ok
    if dns_err:
        result.errors.append(f"DNS: {dns_err}")

    if dns_ok:
        tcp_ok, tcp_err = probe_tcp(host, port)
        result.tcp_ok = tcp_ok
        if tcp_err:
            result.errors.append(f"TCP {port}: {tcp_err}")

    raw_ok, raw_err, first = probe_raw_websocket(session_url)
    result.raw_ws_ok = raw_ok
    result.raw_first_packet = first
    if raw_err:
        result.errors.append(f"raw WS: {raw_err}")

    if not raw_ok:
        return result

    if fetch_fresh_url is None:
        result.errors.append(
            "socket.io: raw WS 후 동일 auth URL 재사용 불가 — fetch_fresh_url 필요"
        )
        return result

    try:
        socketio_url = fetch_fresh_url()
        logger.info("Socket.IO용 새 session URL 발급: %s...", socketio_url[:60])
    except Exception as exc:
        result.errors.append(f"socket.io: 새 session URL 발급 실패: {exc}")
        return result

    sio = socketio.Client(
        reconnection=False,
        logger=socketio_logger,
        engineio_logger=socketio_logger,
        ssl_verify=ssl_ca_bundle(),
    )
    system_payload: dict[str, Any] | None = None
    connect_errors: list[str] = []

    @sio.on("connect")
    def on_connect() -> None:
        logger.info("Socket.IO connect (transport=%s)", getattr(sio, "transport", "?"))

    @sio.on("connect_error")
    def on_connect_error(data: Any) -> None:
        connect_errors.append(str(data))

    @sio.on("SYSTEM")
    def on_system(data: Any) -> None:
        nonlocal system_payload
        payload = normalize_payload(data)
        if payload.get("type") == "connected":
            system_payload = payload

    try:
        sio.connect(socketio_url, transports=["websocket"])
        deadline = time.time() + 15
        while time.time() < deadline and system_payload is None and sio.connected:
            time.sleep(0.1)
        result.socketio_ok = sio.connected and system_payload is not None
        result.system_payload = system_payload
        if connect_errors:
            result.errors.append(f"socket.io: {connect_errors[0]}")
        if sio.connected and system_payload is None:
            result.errors.append("socket.io: SYSTEM connected 타임아웃")
    except Exception as exc:
        detail = exc.__cause__ or exc
        result.errors.append(f"socket.io: {exc} ({detail})")
    finally:
        if sio.connected:
            sio.disconnect()

    return result


def normalize_payload(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return data
    if isinstance(data, (list, tuple)) and data:
        first = data[0]
        if isinstance(first, dict):
            return first
        if isinstance(first, str):
            return json.loads(first)
    if isinstance(data, str):
        return json.loads(data)
    return {"value": data}
