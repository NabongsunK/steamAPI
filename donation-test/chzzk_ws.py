"""치지직 Session WebSocket 연결·진단 유틸."""

from __future__ import annotations

import json
import logging
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import quote, urlencode, urlparse

import certifi

logger = logging.getLogger(__name__)

# 맥미니에서 debug 출력으로 코드 동기화 여부 확인용
WS_MODULE_VERSION = "2026-06-13-v8"


class ChzzkWsAuthError(Exception):
    """WebSocket session URL의 auth 토큰 거부 (만료·재사용·OAuth 무효)."""


def ssl_ca_bundle() -> str:
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
    trace_packets: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.socketio_ok


class ChzzkSessionClient:
    """websocket-client로 Engine.IO v3 + Socket.IO v2 직접 연결."""

    def __init__(self) -> None:
        self._ws: Any = None
        self._session_key: str | None = None
        self._pending_events: list[SessionEvent] = []

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

        self._pending_events = []
        ws_url = build_engineio_ws_url(session_url)
        logger.info("Engine.IO WS query (앞 70자): %s...", ws_url.split("?", 1)[-1][:70])
        self._ws = websocket.create_connection(
            ws_url,
            timeout=timeout,
            sslopt=websocket_sslopt(),
        )
        self._ws.settimeout(1.0)

        open_packet = _decode_packet(self._ws.recv())
        if not open_packet.startswith("0"):
            self.close()
            raise RuntimeError(f"Engine.IO open 실패: {open_packet[:120]!r}")

        logger.info("Engine.IO open OK: %s", open_packet[:100])

        for raw in self._recv_burst(max_wait=0.4, max_packets=10):
            self._ingest_raw(raw)

        if self._session_key:
            logger.info("40 전송 생략 — 이미 SYSTEM connected")
            return

        self._ws.send("40")
        logger.info("Socket.IO namespace connect (40) 전송")

        deadline = time.time() + timeout
        while time.time() < deadline and not self._session_key:
            for raw in self._recv_burst(max_wait=0.5, max_packets=20):
                self._ingest_raw(raw)

        if not self._session_key:
            raise TimeoutError(
                "SYSTEM connected 타임아웃 — error/auth fail 후 sessionKey 미수신"
            )
        logger.info("SYSTEM connected (sessionKey=%s...)", self._session_key[:8])

    def _ingest_raw(self, raw: str) -> None:
        logger.debug("WS recv: %r", raw[:240])
        event = self._process_raw(raw)
        if event:
            self._pending_events.append(event)

    def _recv_burst(self, *, max_wait: float, max_packets: int) -> list[str]:
        if not self._ws:
            return []
        packets: list[str] = []
        self._ws.settimeout(max_wait)
        for _ in range(max_packets):
            try:
                packets.append(_decode_packet(self._ws.recv()))
            except Exception:
                break
        self._ws.settimeout(1.0)
        return packets

    def connect_fresh(
        self,
        access_token: str,
        fetch_session_url: Callable[[str], str],
        *,
        timeout: float = 20.0,
    ) -> str:
        """session URL 발급 직후 즉시 연결 (auth 만료 방지)."""
        session_url = fetch_session_url(access_token)
        self.connect(session_url, timeout=timeout)
        return session_url

    def read_event(self, *, timeout: float = 1.0) -> SessionEvent | None:
        if not self._ws:
            return None

        if self._pending_events:
            return self._pending_events.pop(0)

        self._ws.settimeout(timeout)
        try:
            raw = _decode_packet(self._ws.recv())
        except Exception as exc:
            if type(exc).__name__ in {"WebSocketTimeoutException", "TimeoutError"}:
                return None
            raise

        return self._process_raw(raw)

    def _process_raw(self, raw: str) -> SessionEvent | None:
        _handle_ping(raw, self._ws)

        for packet in _extract_event_packets(raw):
            event = self._packet_to_event(packet)
            if event:
                return event
        return None

    def _packet_to_event(self, packet: str) -> SessionEvent | None:
        if not packet.startswith("42["):
            return None

        try:
            body = json.loads(packet[2:])
        except json.JSONDecodeError as exc:
            raise ValueError(f"Socket.IO JSON 파싱 실패: {packet[:200]!r}") from exc

        if not isinstance(body, list) or not body:
            return None

        name = str(body[0])
        data = body[1] if len(body) > 1 else None

        if name == "error":
            logger.warning("Socket.IO error 이벤트 (무시·재연결 대기): %s", data)
            return None

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


def _auth_fail_message() -> str:
    return (
        "치지직 WebSocket auth 최종 실패 — "
        "Scope '후원 조회'·OAuth 재로그인 확인"
    )


def extract_auth_token(session_url: str) -> str:
    """parse_qs는 auth 토큰의 '+'를 공백으로 바꿔 auth fail 유발 — 문자열로 직접 추출."""
    marker = "auth="
    idx = session_url.find(marker)
    if idx == -1:
        raise ValueError(f"auth= 없음: {session_url[:80]}...")
    rest = session_url[idx + len(marker):]
    amp = rest.find("&")
    token = rest[:amp] if amp != -1 else rest
    if not token:
        raise ValueError("auth 토큰 비어 있음")
    return token


def parse_session_url(session_url: str) -> tuple[str, int, str]:
    parsed = urlparse(session_url)
    host = parsed.hostname or ""
    port = parsed.port or 443
    auth = extract_auth_token(session_url)
    if not host:
        raise ValueError(f"session URL 형식 오류: {session_url[:80]}...")
    return host, port, auth


def build_engineio_ws_url(session_url: str) -> str:
    """API가 준 session URL의 query(auth=...)를 재인코딩하지 않고 그대로 사용."""
    parsed = urlparse(session_url)
    host = parsed.hostname or ""
    port = parsed.port or 443
    if not host or not parsed.query:
        raise ValueError(f"session URL query 없음: {session_url[:80]}...")
    extra = urlencode({"transport": "websocket", "EIO": "3"}, quote_via=quote)
    query = f"{parsed.query}&{extra}"
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
    try:
        import websocket
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


def trace_session_packets(
    session_url: str,
    *,
    timeout: float = 15.0,
) -> list[str]:
    """연결 후 수신 패킷을 모두 기록 (디버그용)."""
    try:
        import websocket
    except ImportError:
        return ["websocket-client 미설치"]

    trace: list[str] = []
    ws_url = build_engineio_ws_url(session_url)
    ws = websocket.create_connection(ws_url, timeout=timeout, sslopt=websocket_sslopt())
    ws.settimeout(1.0)

    try:
        trace.append(f"recv: {_decode_packet(ws.recv())!r}")
        ws.send("40")
        trace.append("send: 40")

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = _decode_packet(ws.recv())
                trace.append(f"recv: {raw!r}")
                if "42[" in raw and "connected" in raw:
                    break
            except Exception as exc:
                if type(exc).__name__ in {"WebSocketTimeoutException", "TimeoutError"}:
                    continue
                trace.append(f"error: {exc}")
                break
    finally:
        ws.close()

    return trace


def probe_socketio_session(
    session_url: str,
    *,
    timeout: float = 20.0,
) -> tuple[bool, dict[str, Any] | None, str | None, list[str]]:
    client = ChzzkSessionClient()
    trace: list[str] = []
    try:
        client.connect(session_url, timeout=timeout)
        if client.session_key:
            payload = {"type": "connected", "data": {"sessionKey": client.session_key}}
            return True, payload, None, trace
        return False, None, "sessionKey 없음", trace
    except Exception as exc:
        trace.extend(trace_session_packets(session_url, timeout=10))
        return False, None, f"{type(exc).__name__}: {exc}", trace
    finally:
        client.close()


def probe_session_connection(
    session_url: str,
    *,
    active_sessions: int | None = None,
    fetch_fresh_url: Callable[[], str] | None = None,
) -> WsProbeResult:
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
            print(f"→ Engine.IO용 새 session URL 발급: {socketio_url.split('?')[0]}")
        except Exception as exc:
            result.errors.append(f"session: 새 URL 발급 실패: {exc}")
            return result

    ok, system_payload, err, trace = probe_socketio_session(socketio_url)
    result.socketio_ok = ok
    result.system_payload = system_payload
    result.trace_packets = trace
    if err:
        result.errors.append(f"Engine.IO session: {err}")

    return result


def _decode_packet(raw: Any) -> str:
    if isinstance(raw, bytes):
        return raw.decode("utf-8")
    return str(raw)


def _handle_ping(raw: str, ws: Any) -> None:
    if not ws:
        return
    if raw == "2":
        ws.send("3")
    elif raw == "2probe":
        ws.send("3probe")


def _extract_event_packets(buf: str) -> list[str]:
    """버퍼에서 42[...] Socket.IO event 패킷만 추출."""
    packets: list[str] = []
    pos = 0
    while True:
        idx = buf.find("42[", pos)
        if idx == -1:
            break
        end = _find_json_array_end(buf, idx + 2)
        if end is None:
            break
        packets.append(buf[idx:end])
        pos = end
    return packets


def _find_json_array_end(buf: str, start: int) -> int | None:
    if start >= len(buf) or buf[start] != "[":
        return None

    depth = 0
    in_string = False
    escape = False
    i = start

    while i < len(buf):
        ch = buf[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return None


def normalize_payload(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return data
    if isinstance(data, str):
        text = data.strip()
        if not text:
            return {"value": ""}
        if not (text.startswith("{") or text.startswith("[")):
            return {"type": "error", "message": text}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"type": "error", "message": text}
        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}
    if data is None:
        return {"value": None}
    return {"value": data}
