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
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from chzzk_api import (
    ChzzkApiError,
    build_auth_url,
    exchange_code,
    new_oauth_state,
    refresh_access_token,
)
from donation_listener import DonationListener

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

oauth_states: set[str] = set()
_tokens: dict[str, Any] = {}

app = FastAPI(title="Chzzk Donation Test Server")


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


listener = DonationListener(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    get_tokens=_get_tokens,
    save_tokens=_save_tokens,
    refresh_tokens=refresh_access_token,
)


@app.on_event("startup")
async def startup() -> None:
    _get_tokens()
    listener.start()
    logger.info("후원 리스너 백그라운드 시작")


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    tokens = _get_tokens()
    has_token = bool(tokens and tokens.get("access_token"))
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
  <p>상태: <strong>{listener.status}</strong></p>
  <p>OAuth: <span class="{'ok' if has_token else 'warn'}">{'연결됨' if has_token else '미연결'}</span></p>
  <ol>
    <li>치지직 앱에 Redirect URI 등록: <code>{REDIRECT_URI}</code></li>
    <li>Scope에 <strong>후원 조회</strong> 체크</li>
    <li><a href="/auth/chzzk">치지직 로그인 (OAuth)</a></li>
    <li>본인 채널에 후원 테스트</li>
  </ol>
  <p><a href="/status">/status</a> · <a href="/donations">/donations</a></p>
</body>
</html>
"""


@app.get("/auth/chzzk")
async def auth_chzzk() -> RedirectResponse:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise HTTPException(500, "CHZZK_CLIENT_ID / CHZZK_CLIENT_SECRET 을 .env 에 설정하세요.")

    state = new_oauth_state()
    oauth_states.add(state)
    url = build_auth_url(CLIENT_ID, REDIRECT_URI, state)
    return RedirectResponse(url)


@app.get("/auth/chzzk/callback")
async def auth_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        raise HTTPException(400, f"OAuth 실패: {error}")
    if not code or not state:
        raise HTTPException(400, "code 또는 state 가 없습니다.")
    if state not in oauth_states:
        raise HTTPException(400, "state 불일치 — /auth/chzzk 부터 다시 시작하세요.")
    oauth_states.discard(state)

    try:
        token_data = await exchange_code(CLIENT_ID, CLIENT_SECRET, code, state)
    except ChzzkApiError as exc:
        raise HTTPException(400, str(exc)) from exc

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


@app.get("/status")
async def status() -> dict[str, Any]:
    tokens = _get_tokens()
    return {
        "listener_status": listener.status,
        "session_key": listener.session_key,
        "last_error": listener.last_error,
        "has_access_token": bool(tokens and tokens.get("access_token")),
        "redirect_uri": REDIRECT_URI,
    }


@app.get("/donations")
async def donations() -> dict[str, Any]:
    items = [
        {
            "received_at": d.received_at,
            "donator_nickname": d.donator_nickname,
            "pay_amount": d.pay_amount,
            "donation_text": d.donation_text,
            "donation_type": d.donation_type,
            "channel_id": d.channel_id,
        }
        for d in listener.recent_donations()
    ]
    return {"count": len(items), "donations": items}


@app.post("/listener/restart")
async def restart_listener() -> dict[str, str]:
    listener.stop()
    listener.start()
    return {"message": "listener restarted"}


def main() -> None:
    if not CLIENT_ID or not CLIENT_SECRET:
        logger.warning(".env 파일에 CHZZK_CLIENT_ID, CHZZK_CLIENT_SECRET 을 넣어주세요.")
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, reload=False)


if __name__ == "__main__":
    main()
