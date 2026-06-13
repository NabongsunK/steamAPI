#!/usr/bin/env python3
"""WebSocket auth fail 원인 좁히기 — server.py 중지 후 단독 실행."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from chzzk_api import get_session_url_sync
from chzzk_ws import (
    WS_MODULE_VERSION,
    build_engineio_ws_url,
    extract_auth_token,
    trace_session_packets,
)

TOKEN_FILE = Path("data/tokens.json")


def main() -> int:
    print(f"chzzk_ws 버전: {WS_MODULE_VERSION}")

    if not TOKEN_FILE.exists():
        print("❌ data/tokens.json 없음 — OAuth 먼저")
        return 1

    token = json.loads(TOKEN_FILE.read_text(encoding="utf-8")).get("access_token")
    if not token:
        print("❌ access_token 없음")
        return 1

    session_url = get_session_url_sync(token)
    auth = extract_auth_token(session_url)
    print(f"session 호스트: {session_url.split('?')[0]}")
    print(f"auth 길이: {len(auth)}, 공백 포함: {' ' in auth}, + 포함: {'+' in auth}")
    print(f"WS URL query (앞 80): {build_engineio_ws_url(session_url).split('?', 1)[-1][:80]}")

  # python-socketio 비교
    print("\n--- python-socketio 연결 시도 ---")
    try:
        import certifi
        import socketio

        sio = socketio.Client(reconnection=False, ssl_verify=certifi.where())
        try:
            sio.connect(session_url, transports=["websocket"])
            print(f"✅ socketio connected={sio.connected}")
            sio.disconnect()
        except Exception as exc:
            print(f"❌ socketio: {exc}")
    except ImportError:
        print("⚠️ python-socketio 없음")

    print("\n--- raw 패킷 추적 (40 전송) ---")
    trace = trace_session_packets(session_url, timeout=8)
    for line in trace:
        print(line)
    if any("sessionKey" in line for line in trace):
        print("\n✅ SYSTEM connected — server.py 실행 가능")
    else:
        print("\n❌ sessionKey 미수신")

    return 0


if __name__ == "__main__":
    sys.exit(main())
