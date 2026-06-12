#!/usr/bin/env python3
"""
치지직 API / WebSocket 단계별 확인 스크립트.

사용:
  cd donation-test
  source .venv/bin/activate
  pip install -r requirements.txt
  python3 debug_chzzk.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

from chzzk_ws import (
    build_engineio_ws_url,
    parse_session_url,
    probe_session_connection,
)

load_dotenv()

API_BASE = "https://openapi.chzzk.naver.com"
TOKEN_FILE = Path(os.getenv("TOKEN_FILE", "data/tokens.json"))


def _print_section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def check_dependencies() -> bool:
    _print_section("0) Python 패키지 확인")
    ok = True

    try:
        import socketio

        print(f"✅ python-socketio {getattr(socketio, '__version__', '?')}")
    except ImportError:
        print("❌ python-socketio 없음")
        ok = False

    try:
        import engineio

        print(f"✅ python-engineio {getattr(engineio, '__version__', '?')}")
    except ImportError:
        print("❌ python-engineio 없음")
        ok = False

    try:
        import websocket

        print(f"✅ websocket-client {getattr(websocket, '__version__', '?')}")
    except ImportError:
        print("❌ websocket-client 없음 → pip install websocket-client")
        ok = False

    try:
        import requests  # noqa: F401 — engineio polling fallback용

        print("✅ requests 설치됨")
    except ImportError:
        print("⚠️ requests 없음 (polling 진단 시 필요) → pip install requests")

    try:
        import certifi

        print(f"✅ certifi CA bundle: {certifi.where()}")
    except ImportError:
        print("❌ certifi 없음 → pip install certifi")
        ok = False

    print(f"Python: {sys.version.split()[0]}")
    return ok


def _load_token() -> str | None:
    if not TOKEN_FILE.exists():
        return None
    data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    return data.get("access_token")


def check_token_file() -> str | None:
    _print_section("1) 로컬 토큰 (data/tokens.json)")
    if not TOKEN_FILE.exists():
        print("❌ 없음 → https://wwmw.shop/auth/chzzk 로 OAuth 먼저")
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

    host, port, auth = parse_session_url(session_url)
    print(f"✅ session 호스트: {host}:{port}")
    print(f"   auth 토큰 길이: {len(auth)}")
    print(f"   Engine.IO WS URL (앞 90자): {build_engineio_ws_url(session_url)[:90]}...")
    return session_url


def check_session_list(access_token: str) -> int:
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
    active = 0
    try:
        body = resp.json()
        print(json.dumps(body, ensure_ascii=False, indent=2))
        data = (body.get("content") or {}).get("data") or body.get("data") or []
        active_list = [s for s in data if not s.get("disconnectedDate")]
        active = len(active_list)
        print(f"→ 활성(끊기지 않은) 세션: {active}개 / 최대 3개")
        if active >= 3:
            print("⚠️ 세션 3개 꽉 참 — server.py 중지 후 1~2분 대기하거나 /auth/reset")
    except json.JSONDecodeError:
        print(resp.text[:500])
    return active


def check_websocket(session_url: str, active_sessions: int) -> None:
    _print_section("4) WebSocket — DNS → TCP → raw WS → Socket.IO")
    print("세션 URL은 발급 직후 바로 연결해야 합니다 (30초~1분 내 미연결 시 만료).")
    print(f"현재 활성 세션: {active_sessions}개\n")

    result = probe_session_connection(
        session_url,
        active_sessions=active_sessions,
        socketio_logger=True,
    )

    print(f"DNS ({result.host}): {'✅' if result.dns_ok else '❌'}")
    print(f"TCP ({result.host}:{result.port}): {'✅' if result.tcp_ok else '❌'}")
    print(f"raw WebSocket: {'✅' if result.raw_ws_ok else '❌'}")
    if result.raw_first_packet:
        print(f"   첫 패킷: {result.raw_first_packet!r}")
    print(f"Socket.IO + SYSTEM connected: {'✅' if result.socketio_ok else '❌'}")
    if result.system_payload:
        sk = (result.system_payload.get("data") or {}).get("sessionKey", "")
        print(f"   sessionKey: {sk[:12]}..." if sk else "   sessionKey 없음")

    if result.errors:
        print("\n오류 상세:")
        for err in result.errors:
            print(f"  • {err}")

    if not result.ok:
        print("\n진단 힌트:")
        if any("SSLCertVerificationError" in e or "CERTIFICATE_VERIFY_FAILED" in e for e in result.errors):
            print("  - SSL 인증서 검증 실패 → macOS Python CA 미설치가 흔한 원인")
            print("    1) pip install certifi 후 debug_chzzk.py 재실행 (코드에 반영됨)")
            print("    2) /Applications/Python\\ 3.13/Install\\ Certificates.command 실행")
        elif not result.dns_ok:
            print("  - DNS 실패 → 맥미니/서버 DNS 설정 확인")
        elif not result.tcp_ok:
            print("  - TCP 443 실패 → 방화벽·ISP·ssio*.nchat.naver.com 차단 의심")
        elif not result.raw_ws_ok:
            print("  - raw WS 실패 → TLS/핸드셰이크 거부 (세션 만료·auth 무효·3개 초과)")
        else:
            print("  - raw WS는 OK인데 Socket.IO만 실패 → python-socketio/engineio 버전 확인")
        if active_sessions >= 3:
            print("  - 활성 세션 3개 → 재시도 루프 중지 후 잠시 대기")


def main() -> int:
    if not check_dependencies():
        return 1

    token = check_token_file()
    if not token:
        return 1

    session_url = check_session_auth(token)
    active = check_session_list(token)

    if session_url:
        check_websocket(session_url, active)
    else:
        print("\n⚠️ session URL 없어서 WebSocket 테스트 생략")

    _print_section("요약")
    print("• 2번 REST 200 + url → Open API·OAuth는 정상")
    print("• 4번에서 DNS/TCP/raw WS/Socket.IO 중 어디서 끊기는지 확인")
    print("• server.py가 10초마다 재시도 중이면 세션 URL 낭비 → 먼저 pkill 후 이 스크립트 실행")
    return 0


if __name__ == "__main__":
    sys.exit(main())
