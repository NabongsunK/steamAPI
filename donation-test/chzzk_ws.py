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

logger = logging.getLogger(__name__)


def ssl_ca_bundle() -> str:
    """macOS python.org 빌드 등에서 시스템 CA가 비어 있을 때 certifi 사용."""
    return certifi.where()


def websocket_sslopt() -> dict[str, str]:
    return {"ca_certs": ssl_ca_bundle()}


@dataclass
class SessionEvent:
    name: str
    payload: dict[str, Any]


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


class ChzzkSessionClient:
    """websocket-client로 Engine.IO v3 + Socket.IO v2 직접 연결 (python-socketio 미사용)."""

    def __init__(self) -> None:
        self._ws: Any = None
        self._session_key: str | None = None
        self._pending_packets: list[str] = []

    @property
    def session_key(self) -> str | None:
        return self._session_key

    @property
    def connected(self) -> bool:
        return self._ws is not None

    def connect(self, session_url: str, *, timeout: float = 20.0) -> None:
        try:
            import websocket
        except ImportError as exc:
            raise RuntimeError("websocket-client 미설치") from exc

        ws_url = build_engineio_ws_url(session_url)
        self._ws = websocket.create_connection(
            ws_url,
            timeout=timeout,
            sslopt=websocket_sslopt(),
        )
        self._ws.settimeout(1.0)
        self._pending_packets = []

        open_packet = _decode_packet(self._ws.recv())
        if not open_packet.startswith("0"):
            self.close()
            raise RuntimeError(f"Engine.IO open 실패: {open_packet[:120]!r}")

        _engineio_probe_handshake(self._ws)
        self._ws.send("40")

    def read_event(self, *, timeout: float = 1.0) -> SessionEvent | None:
        if not self._ws:
            return None

        if self._pending_packets:
            packet = self._pending_packets.pop(0)
            return self._packet_to_event(packet)

        self._ws.settimeout(timeout)
        try:
            raw = _decode_packet(self._ws.recv())
        except Exception as exc:
            exc_name = type(exc).__name__
            if exc_name in {"WebSocketTimeoutException", "TimeoutError"}:
                return None
            raise

        for packet in _split_engineio_packets(raw):
            event = self._packet_to_event(packet)
            if event:
                return event
        return None

    def _packet_to_event(self, packet: str) -> SessionEvent | None:
        if packet == "2" or packet == "2probe":
            if self._ws:
                self._ws.send("3" if packet == "2" else "3probe")
            return None

        if packet.startswith("40") or packet.startswith("41") or packet.startswith("44"):
            logger.debug("Socket.IO control packet: %s", packet[:120])
            return None

        parsed = _parse_socketio_event(packet)
        if not parsed:
            return None

        name, data = parsed
        payload = normalize_payload(data)
        if name == "SYSTEM" and payload.get("type") == "connected":
            session_key = (payload.get("data") or {}).get("sessionKey")
            if session_key:
                self._session_key = session_key
        return SessionEvent(name=name, payload=payload)

    def wait_for(
        self,
        *,
        predicate: Callable[[SessionEvent], bool],
        timeout: float = 20.0,
    ) -> SessionEvent:
        deadline = time.time() + timeout
        while time.time() < deadline:
            event = self.read_event(timeout=min(1.0, max(0.1, deadline - time.time())))
            if event and predicate(event):
                return event
        raise TimeoutError("이벤트 대기 타임아웃")

    def close(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None


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


def probe_socketio_session(
    session_url: str,
    *,
    timeout: float = 20.0,
) -> tuple[bool, dict[str, Any] | None, str | None]:
    """Engine.IO 직접 연결 후 SYSTEM connected 확인."""
    client = ChzzkSessionClient()
    try:
        client.connect(session_url, timeout=timeout)
        event = client.wait_for(
            predicate=lambda ev: ev.name == "SYSTEM" and ev.payload.get("type") == "connected",
            timeout=timeout,
        )
        return True, event.payload, None
    except Exception as exc:
        return False, None, f"{type(exc).__name__}: {exc}"
    finally:
        client.close()


def probe_session_connection(
    session_url: str,
    *,
    active_sessions: int | None = None,
    fetch_fresh_url: Callable[[], str] | None = None,
) -> WsProbeResult:
    """세션 URL 진단.

    raw WS와 Socket.IO는 auth 토큰이 1회용이라 **서로 다른 URL**이 필요합니다.
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

    socketio_url = session_url
    if fetch_fresh_url is not None:
        try:
            socketio_url = fetch_fresh_url()
            print(f"→ Socket.IO용 새 session URL 발급: {socketio_url.split('?')[0]}")
        except Exception as exc:
            result.errors.append(f"session: 새 URL 발급 실패: {exc}")
            return result

    ok, system_payload, err = probe_socketio_session(socketio_url)
    result.socketio_ok = ok
    result.system_payload = system_payload
    if err:
        result.errors.append(f"Engine.IO session: {err}")

    return result


def _decode_packet(raw: Any) -> str:
    if isinstance(raw, bytes):
        return raw.decode("utf-8")
    return str(raw)


def _engineio_probe_handshake(ws: Any) -> None:
    """open(0) 이후 probe → upgrade (CHZZK open에 upgrades 포함 시)."""
    ws.settimeout(0.5)
    try:
        ws.send("2probe")
        resp = _decode_packet(ws.recv())
        if resp == "3probe":
            ws.send("5")
        elif resp.startswith("2"):
            ws.send("3probe" if resp == "2probe" else "3")
        else:
            logger.debug("probe 응답 없음/다른 패킷: %r", resp[:80])
    except Exception:
        pass
    ws.settimeout(1.0)


def _split_engineio_packets(buf: str) -> list[str]:
    """한 WebSocket 프레임에 붙은 Engine.IO 패킷 분리 (예: 40{...}42[...])."""
    packets: list[str] = []
    i = 0
    n = len(buf)

    while i < n:
        if not buf[i].isdigit():
            i += 1
            continue

        start = i
        pkt_type = int(buf[i])
        i += 1

        if pkt_type == 4 and i < n and buf[i].isdigit():
            i += 1
            i = _skip_json_value(buf, i)
        elif pkt_type == 0 and i < n and buf[i] == "{":
            i = _skip_json_value(buf, i)
        elif pkt_type in (2, 3):
            while i < n and buf[i].isalpha():
                i += 1

        packets.append(buf[start:i])

    return packets if packets else [buf]


def _skip_json_value(buf: str, i: int) -> int:
    n = len(buf)
    if i >= n:
        return i

    ch = buf[i]
    if ch == "{":
        depth = 0
        while i < n:
            if buf[i] == "{":
                depth += 1
            elif buf[i] == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        return n

    if ch == "[":
        depth = 0
        while i < n:
            if buf[i] == "[":
                depth += 1
            elif buf[i] == "]":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        return n

    if ch == '"':
        i += 1
        while i < n:
            if buf[i] == "\\":
                i += 2
                continue
            if buf[i] == '"':
                return i + 1
            i += 1
        return n

    return i


def _parse_socketio_event(packet: str) -> tuple[str, Any] | None:
    if not packet.startswith("42"):
        return None
    body_text = packet[2:]
    if not body_text:
        return None
    try:
        body = json.loads(body_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Socket.IO event JSON 파싱 실패: {packet[:160]!r}") from exc
    if not isinstance(body, list) or not body:
        return None
    name = str(body[0])
    data = body[1] if len(body) > 1 else None
    return name, data


def normalize_payload(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return data
    if isinstance(data, (list, tuple)) and data:
        first = data[0]
        if isinstance(first, dict):
            return first
        if isinstance(first, str) and first:
            return json.loads(first)
    if isinstance(data, str) and data:
        return json.loads(data)
    return {"value": data}
