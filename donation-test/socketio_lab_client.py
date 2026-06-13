#!/usr/bin/env python3
"""
Socket.IO 클라이언트 테스트 (치지직 무관, python-socketio).

  # 같은 PC
  python socketio_lab_server.py
  python socketio_lab_client.py

  # 맥미니 서버 + 개발 PC 클라이언트
  python socketio_lab_client.py http://100.73.52.88:8765

  # raw Engine.IO (websocket-client, CHZZK와 비슷한 수동 패킷)
  python socketio_lab_client.py --raw http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from urllib.parse import urlencode, urlparse

import socketio


def _machine_label() -> str:
    return f"{platform.node()} ({platform.system()})"


def run_socketio_client(url: str, timeout: float) -> bool:
    got_pong = False
    client = socketio.Client(logger=False, engineio_logger=False)

    @client.event
    def connect() -> None:
        print("  python-socketio: connected")
        client.emit("ping_test", {"from": _machine_label(), "ts": time.time()})

    @client.on("pong_test")
    def on_pong(data: dict) -> None:
        nonlocal got_pong
        got_pong = True
        print(f"  python-socketio: pong_test {json.dumps(data, ensure_ascii=False)}")

    @client.event
    def connect_error(data) -> None:
        print(f"  python-socketio: connect_error {data!r}")

    try:
        client.connect(url, transports=["websocket"], wait_timeout=timeout)
        deadline = time.time() + timeout
        while time.time() < deadline and client.connected and not got_pong:
            time.sleep(0.1)
        client.disconnect()
    except Exception as exc:
        print(f"  python-socketio: FAIL {type(exc).__name__}: {exc}")
        return False

    return got_pong


def _http_to_ws_url(base_url: str, eio: str = "4") -> str:
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    query = urlencode({"EIO": eio, "transport": "websocket"})
    return f"{scheme}://{host}:{port}/socket.io/?{query}"


def run_raw_client(url: str, timeout: float) -> bool:
    try:
        import websocket
    except ImportError:
        print("  raw: websocket-client 미설치")
        return False

    ws_url = _http_to_ws_url(url)
    print(f"  raw WS URL: {ws_url}")

    try:
        ws = websocket.create_connection(ws_url, timeout=timeout)
        ws.settimeout(2.0)

        open_pkt = ws.recv()
        open_text = open_pkt.decode() if isinstance(open_pkt, bytes) else str(open_pkt)
        print(f"  raw: recv {open_text[:120]!r}")
        if not open_text.startswith("0"):
            ws.close()
            print("  raw: FAIL — Engine.IO open 패킷 아님")
            return False

        ws.send("40")
        print("  raw: send 40")

        connected = False
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = ws.recv()
                text = raw.decode() if isinstance(raw, bytes) else str(raw)
                print(f"  raw: recv {text[:160]!r}")
                if text == "40" or text.startswith("40"):
                    connected = True
                    break
            except Exception:
                continue

        if not connected:
            ws.close()
            print("  raw: FAIL — namespace connect(40) 응답 없음")
            return False

        payload = json.dumps(["ping_test", {"from": _machine_label(), "mode": "raw"}])
        ws.send(f"42{payload}")
        print(f"  raw: send 42{payload}")

        got_pong = False
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = ws.recv()
                text = raw.decode() if isinstance(raw, bytes) else str(raw)
                print(f"  raw: recv {text[:200]!r}")
                if "pong_test" in text:
                    got_pong = True
                    break
            except Exception:
                continue

        ws.close()
        if not got_pong:
            print("  raw: FAIL — pong_test 미수신")
        return got_pong
    except Exception as exc:
        print(f"  raw: FAIL {type(exc).__name__}: {exc}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Socket.IO lab 클라이언트")
    parser.add_argument(
        "url",
        nargs="?",
        default="http://127.0.0.1:8765",
        help="서버 URL (기본 http://127.0.0.1:8765)",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="타임아웃(초)")
    parser.add_argument(
        "--raw",
        action="store_true",
        help="python-socketio 대신 websocket-client로 수동 패킷",
    )
    parser.add_argument(
        "--both",
        action="store_true",
        help="python-socketio + raw 둘 다 실행",
    )
    args = parser.parse_args()

    print("=" * 56)
    print("Socket.IO lab 클라이언트 (치지직 무관)")
    print("=" * 56)
    print(f"머신:   {_machine_label()}")
    print(f"서버:   {args.url}")

    ok = False
    if args.raw and not args.both:
        ok = run_raw_client(args.url, args.timeout)
    elif args.both:
        sio_ok = run_socketio_client(args.url, args.timeout)
        raw_ok = run_raw_client(args.url, args.timeout)
        ok = sio_ok and raw_ok
        print(f"\n  python-socketio: {'OK' if sio_ok else 'FAIL'}")
        print(f"  raw websocket:   {'OK' if raw_ok else 'FAIL'}")
    else:
        ok = run_socketio_client(args.url, args.timeout)

    print("-" * 56)
    if ok:
        print("결과: SUCCESS")
    else:
        print("결과: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
