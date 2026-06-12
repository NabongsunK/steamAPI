#!/usr/bin/env python3
"""
치지직 API / WebSocket 단계별 확인 스크립트.

사용:
  cd donation-test
  source .venv/bin/activate
  python3 debug_chzzk.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

API_BASE = "https://openapi.chzzk.naver.com"
TOKEN_FILE = Path(os.getenv("TOKEN_FILE", "data/tokens.json"))


def _load_token() -> str | None:
    if not TOKEN_FILE.exists():
        return None
    data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    return data.get("access_token")


def _print_section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def check_token_file() -> str | None:
    _print_section("1) 로컬 토큰 (data/tokens.json)")
    if not TOKEN_FILE.exists():
        print("❌ 없음 → /auth/chzzk 로 OAuth 먼저")
        return None
    data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    token = data.get("access_token", "")
    print(f"✅ access_token 앞 20자: {token[:20]}...")
    print(f"   expires_in: {data.get('expires_in')}")
    return token


def check_session_auth(access_token: str) -> str | None:
    _print_section("2) 치지직 REST — GET /open/v1/sessions/auth")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    url = f"{API_BASE}/open/v1/sessions/auth"
    print(f"요청: GET {url}")

    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=headers)

    print(f"HTTP 상태: {resp.status_code}")
    print("응답 body:")
    try:
        body = resp.json()
        print(json.dumps(body, ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print(resp.text[:500])
        return None

    if resp.status_code != 200:
        print("❌ REST 실패")
        return None

    content = body.get("content") or {}
    session_url = content.get("url")
    if body.get("code") != 200 or not session_url:
        print("❌ code!=200 또는 url 없음")
        return None

    print(f"✅ session URL 호스트: {session_url.split('?')[0]}")
    print(f"   auth 토큰 길이: {len(session_url.split('auth=')[-1]) if 'auth=' in session_url else 0}")
    return session_url


def check_session_list(access_token: str) -> None:
    _print_section("3) 치지직 REST — GET /open/v1/sessions (연결 목록)")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(
            f"{API_BASE}/open/v1/sessions",
            headers=headers,
            params={"size": 10, "page": "0"},
        )

    print(f"HTTP 상태: {resp.status_code}")
    try:
        body = resp.json()
        print(json.dumps(body, ensure_ascii=False, indent=2))
        data = (body.get("content") or {}).get("data") or body.get("data") or []
        active = [s for s in data if not s.get("disconnectedDate")]
        print(f"→ 활성(끊기지 않은) 세션: {len(active)}개 (최대 3개)")
    except json.JSONDecodeError:
        print(resp.text[:500])


def check_websocket(session_url: str) -> None:
    _print_section("4) WebSocket — Socket.IO connect (실제 후원 수신 경로)")
    try:
        import socketio
    except ImportError:
        print("❌ python-socketio 미설치")
        return

    try:
        import websocket  # noqa: F401 — websocket-client
        print("✅ websocket-client 설치됨")
    except ImportError:
        print("❌ websocket-client 없음 → pip install websocket-client")

    print(f"연결 URL (앞 80자): {session_url[:80]}...")

    sio = socketio.Client(reconnection=False, logger=True, engineio_logger=True)
    result = {"connect": False, "system": None, "error": None}

    @sio.on("connect")
    def on_connect() -> None:
        result["connect"] = True
        print("✅ Socket.IO connect 이벤트 수신")

    @sio.on("connect_error")
    def on_connect_error(data) -> None:
        result["error"] = str(data)
        print(f"❌ connect_error: {data}")

    @sio.on("SYSTEM")
    def on_system(data) -> None:
        result["system"] = data
        print(f"✅ SYSTEM 수신: {data}")

    try:
        sio.connect(session_url, transports=["websocket"])
        print(f"sio.connected={sio.connected}, transport={getattr(sio, 'transport', '?')}")
        if sio.connected:
            import time

            time.sleep(3)
        sio.disconnect()
    except Exception as exc:
        print(f"❌ connect 예외: {exc}")
        if result["error"]:
            print(f"   connect_error 상세: {result['error']}")

    if not result["connect"] and not result["system"]:
        print("\n→ REST(2번)는 OK인데 WS(4번)만 실패면:")
        print("  - Scope '후원 조회' / Socket.IO 프로토콜 / WS 3개 초과 의심")
        print("  - engineio 로그 위 EIO=3 handshake 응답 확인")


def main() -> int:
    token = check_token_file()
    if not token:
        return 1

    session_url = check_session_auth(token)
    check_session_list(token)

    if session_url:
        check_websocket(session_url)
    else:
        print("\n⚠️ session URL 없어서 WebSocket 테스트 생략")

    _print_section("요약")
    print("• 2번 REST 200 + url → 치지직 Open API는 정상")
    print("• 4번 Connection error → WS 서버(ssio*.nchat.naver.com) 핸드셰이크 실패")
    print("  (치지직 REST '리턴'이 아니라 WebSocket 연결 단계 문제)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
