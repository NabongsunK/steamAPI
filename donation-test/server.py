"""
치지직 후원 API 테스트 서버.

1. .env 에 Client ID/Secret 설정
2. python server.py
3. 브라우저에서 http://localhost:3000/auth/chzzk
4. 치지직 로그인 후 후원이 오면 콘솔/GET /donations 에 표시
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from chzzk_api import (
    ChzzkApiError,
    build_auth_url,
    exchange_code,
    list_user_sessions_sync,
    new_oauth_state,
    refresh_access_token,
    revoke_token_sync,
)
from donation_listener import DonationListener
from donation_store import DonationStore

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("chzzk-donation-test")

CLIENT_ID = os.getenv("CHZZK_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("CHZZK_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("CHZZK_REDIRECT_URI", "http://localhost:3000/auth/chzzk/callback")
PORT = int(os.getenv("PORT", "3000"))
TOKEN_FILE = Path(os.getenv("TOKEN_FILE", "data/tokens.json"))
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
SQLITE_PATH = Path(os.getenv("SQLITE_PATH", "data/donations.db"))
DONATION_LIST_LIMIT = int(os.getenv("DONATION_LIST_LIMIT", "50"))
STATE_FILE = Path(os.getenv("OAUTH_STATE_FILE", "data/oauth_states.json"))
STATE_TTL_SEC = int(os.getenv("OAUTH_STATE_TTL_SEC", "600"))

oauth_states: set[str] = set()
_tokens: dict[str, Any] = {}

app = FastAPI(title="Chzzk Donation Test Server")

EXPECTED_CALLBACK_SUFFIX = "/auth/chzzk/callback"


def _load_oauth_states() -> dict[str, float]:
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return {k: float(v) for k, v in data.items()}
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def _save_oauth_states(states: dict[str, float]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(states, ensure_ascii=False, indent=2), encoding="utf-8")


def _prune_oauth_states(states: dict[str, float]) -> dict[str, float]:
    now = time.time()
    return {k: v for k, v in states.items() if now - v <= STATE_TTL_SEC}


def _register_oauth_state(state: str) -> None:
    oauth_states.add(state)
    states = _prune_oauth_states(_load_oauth_states())
    states[state] = time.time()
    _save_oauth_states(states)


def _consume_oauth_state(state: str) -> bool:
    states = _prune_oauth_states(_load_oauth_states())
    if state not in states and state not in oauth_states:
        return False
    states.pop(state, None)
    oauth_states.discard(state)
    _save_oauth_states(states)
    return True


def _redirect_uri_ok() -> bool:
    return REDIRECT_URI.rstrip("/").endswith(EXPECTED_CALLBACK_SUFFIX)


def _load_tokens() -> dict[str, Any] | None:
    if TOKEN_FILE.exists():
        try:
            return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    return None


def _save_tokens(data: dict[str, Any]) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _tokens.clear()
    _tokens.update(data)


def _get_tokens() -> dict[str, Any] | None:
    if _tokens:
        return _tokens
    loaded = _load_tokens()
    if loaded:
        _tokens.update(loaded)
    return loaded or None


donation_store = DonationStore(redis_url=REDIS_URL, sqlite_path=SQLITE_PATH)

listener = DonationListener(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    get_tokens=_get_tokens,
    save_tokens=_save_tokens,
    refresh_tokens=refresh_access_token,
    store=donation_store,
)


@app.on_event("startup")
async def startup() -> None:
    _get_tokens()
    if not _redirect_uri_ok():
        logger.warning(
            "CHZZK_REDIRECT_URI가 콜백 경로와 다릅니다. "
            "예: https://wwmw.shop/auth/chzzk/callback (현재: %s)",
            REDIRECT_URI,
        )
    try:
        donation_store.queue.ping()
        donation_store.start_worker()
        logger.info("Redis 연결 OK · 큐 워커 시작")
    except Exception as exc:
        logger.error("Redis 연결 실패 — redis-server 실행 여부 확인: %s", exc)
    listener.start()
    logger.info("후원 리스너 백그라운드 시작")


async def _handle_oauth_callback(
    code: str | None,
    state: str | None,
    error: str | None,
) -> RedirectResponse:
    if error:
        logger.error("OAuth provider error: %s", error)
        raise HTTPException(400, f"OAuth 실패: {error}")
    if not code or not state:
        logger.error("OAuth callback missing code/state (redirect_uri=%s)", REDIRECT_URI)
        raise HTTPException(
            400,
            f"code 또는 state 가 없습니다. CHZZK_REDIRECT_URI가 "
            f"'{REDIRECT_URI}' 인지, 치지직 콘솔과 동일한지 확인하세요.",
        )
    if not _consume_oauth_state(state):
        logger.error("OAuth state mismatch (redirect_uri=%s)", REDIRECT_URI)
        raise HTTPException(
            400,
            "state 불일치 — /auth/chzzk 부터 다시 시작하세요. (서버 재시작 직후면 다시 로그인)",
        )

    try:
        token_data = await exchange_code(CLIENT_ID, CLIENT_SECRET, code, state)
    except ChzzkApiError as exc:
        logger.error("Token exchange failed: %s payload=%s", exc, exc.payload)
        raise HTTPException(
            400,
            f"토큰 발급 실패: {exc}. Redirect URI가 콘솔·.env와 동일한지 확인하세요. (현재: {REDIRECT_URI})",
        ) from exc

    _save_tokens(
        {
            "access_token": token_data["accessToken"],
            "refresh_token": token_data["refreshToken"],
            "token_type": token_data.get("tokenType", "Bearer"),
            "expires_in": int(token_data.get("expiresIn", 86400)),
        }
    )
    logger.info("OAuth 완료 — 후원 리스너가 세션을 연결합니다.")
    listener.start()
    return RedirectResponse("/?oauth=ok")


def _index_html(has_token: bool, redirect_ok: bool, oauth_msg: str = "") -> str:
    oauth_banner = ""
    if oauth_msg == "ok":
        oauth_banner = '<p class="ok"><strong>OAuth 연결 완료!</strong></p>'
    return f"""
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <title>치지직 후원 테스트</title>
  <style>
    body {{ font-family: sans-serif; max-width: 720px; margin: 2rem auto; line-height: 1.6; }}
    code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 4px; }}
    .ok {{ color: #0a7; }} .warn {{ color: #c80; }}
  </style>
</head>
<body>
  <h1>치지직 후원 API 테스트</h1>
  {oauth_banner}
  <p>상태: <strong>{listener.status}</strong></p>
  <p>OAuth: <span class="{'ok' if has_token else 'warn'}">{'연결됨' if has_token else '미연결'}</span></p>
  <p>Redirect URI: <code>{REDIRECT_URI}</code>
    <span class="{'ok' if redirect_ok else 'warn'}">{'OK' if redirect_ok else '경로 확인 필요 (/auth/chzzk/callback)'}</span></p>
  <ol>
    <li>치지직 앱 로그인 리디렉션 URL = 위 Redirect URI와 <strong>완전 동일</strong></li>
    <li>Scope에 <strong>후원 조회</strong> 체크</li>
    <li><a href="/auth/chzzk">치지직 로그인 (OAuth)</a></li>
    <li>본인 채널에 후원 테스트</li>
  </ol>
  <p><a href="/status">/status</a> · <a href="/donations">/donations</a> · <a href="/donations/recent">/donations/recent</a></p>
</body>
</html>
"""


@app.get("/")
async def index(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    oauth: str | None = None,
):
    # 치지직 콘솔 Redirect URI가 루트(/)인 경우: /?code=...&state=... 로 돌아옴
    if code and state:
        logger.info("OAuth callback on / (redirect_uri=%s)", REDIRECT_URI)
        return await _handle_oauth_callback(code, state, error)
    if error:
        raise HTTPException(400, f"OAuth 실패: {error}")

    tokens = _get_tokens()
    has_token = bool(tokens and tokens.get("access_token"))
    redirect_ok = _redirect_uri_ok()
    return HTMLResponse(_index_html(has_token, redirect_ok, oauth or ""))


@app.get("/auth/chzzk")
async def auth_chzzk() -> RedirectResponse:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise HTTPException(500, "CHZZK_CLIENT_ID / CHZZK_CLIENT_SECRET 을 .env 에 설정하세요.")

    state = new_oauth_state()
    _register_oauth_state(state)
    url = build_auth_url(CLIENT_ID, REDIRECT_URI, state)
    logger.info("OAuth 시작 redirect_uri=%s", REDIRECT_URI)
    return RedirectResponse(url)


@app.get("/auth/chzzk/callback")
async def auth_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    return await _handle_oauth_callback(code, state, error)


@app.get("/status")
async def status() -> dict[str, Any]:
    tokens = _get_tokens()
    storage = donation_store.stats()
    return {
        "listener_status": listener.status,
        "session_key": listener.session_key,
        "last_error": listener.last_error,
        "has_access_token": bool(tokens and tokens.get("access_token")),
        "redirect_uri": REDIRECT_URI,
        "redirect_uri_ok": _redirect_uri_ok(),
        "expected_redirect_uri_suffix": EXPECTED_CALLBACK_SUFFIX,
        "storage": storage,
    }


@app.get("/donations")
async def donations(
    limit: int = Query(default=DONATION_LIST_LIMIT, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    items = donation_store.sqlite.list_recent(limit=limit, offset=offset)
    return {
        "source": "sqlite",
        "count": len(items),
        "total": donation_store.sqlite.count(),
        "queue_pending": donation_store.queue.queue_length(),
        "donations": items,
    }


@app.get("/donations/recent")
async def donations_recent(
    limit: int = Query(default=DONATION_LIST_LIMIT, ge=1, le=200),
) -> dict[str, Any]:
    records = donation_store.queue.recent(limit=limit)
    items = [
        {
            "received_at": r.received_at,
            "donator_nickname": r.donator_nickname,
            "pay_amount": r.pay_amount,
            "donation_text": r.donation_text,
            "donation_type": r.donation_type,
            "channel_id": r.channel_id,
            "donator_channel_id": r.donator_channel_id,
        }
        for r in records
    ]
    return {
        "source": "redis",
        "count": len(items),
        "queue_pending": donation_store.queue.queue_length(),
        "donations": items,
    }


@app.post("/listener/restart")
async def restart_listener() -> dict[str, str]:
    listener.stop()
    donation_store.stop_worker()
    donation_store.start_worker()
    listener.start()
    return {"message": "listener and queue worker restarted"}


@app.post("/auth/reset")
async def auth_reset() -> dict[str, Any]:
    """로컬 토큰·OAuth state 삭제 + (가능하면) 치지직 토큰 revoke."""
    listener.stop()
    tokens = _get_tokens()
    revoked = False
    revoke_error: str | None = None
    sessions_before: Any = None

    if tokens and tokens.get("access_token") and CLIENT_ID and CLIENT_SECRET:
        try:
            sessions_before = list_user_sessions_sync(tokens["access_token"])
        except Exception as exc:
            logger.warning("세션 목록 조회 실패: %s", exc)
        try:
            revoke_token_sync(
                CLIENT_ID,
                CLIENT_SECRET,
                tokens["access_token"],
            )
            revoked = True
        except Exception as exc:
            revoke_error = str(exc)
            logger.warning("토큰 revoke 실패: %s", exc)

    _tokens.clear()
    for path in (TOKEN_FILE, STATE_FILE):
        if path.exists():
            path.unlink()

    oauth_states.clear()
    listener.start()

    return {
        "message": "로컬 OAuth/세션 state 초기화 완료. /auth/chzzk 로 다시 로그인하세요.",
        "token_revoked": revoked,
        "revoke_error": revoke_error,
        "sessions_before_reset": sessions_before,
    }


def main() -> None:
    if not CLIENT_ID or not CLIENT_SECRET:
        logger.warning(".env 파일에 CHZZK_CLIENT_ID, CHZZK_CLIENT_SECRET 을 넣어주세요.")
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=False)


if __name__ == "__main__":
    main()
