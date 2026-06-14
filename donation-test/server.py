"""
치지직 후원 API 테스트 서버 (다중 스트리머 uid).

1. .env 에 Client ID/Secret 설정
2. python server.py
3. POST /streamers 로 스트리머 등록 → uid 발급
4. GET /auth/chzzk?uid=<uid> OAuth
5. 본인 채널 후원 → GET /donations?streamer_uid=<uid>
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
from pydantic import BaseModel, Field

from chzzk_api import (
    ChzzkApiError,
    build_auth_url,
    exchange_code,
    list_user_sessions_sync,
    new_oauth_state,
    refresh_access_token,
    revoke_token_sync,
)
from donation_store import DonationStore
from listener_manager import DonationListenerManager
from streamer_store import StreamerStore

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
STREAMERS_DB = Path(os.getenv("STREAMERS_DB", "data/streamers.db"))
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
SQLITE_PATH = Path(os.getenv("SQLITE_PATH", "data/donations.db"))
DONATION_LIST_LIMIT = int(os.getenv("DONATION_LIST_LIMIT", "50"))
STATE_FILE = Path(os.getenv("OAUTH_STATE_FILE", "data/oauth_states.json"))
STATE_TTL_SEC = int(os.getenv("OAUTH_STATE_TTL_SEC", "600"))

oauth_states: set[str] = set()

app = FastAPI(title="Chzzk Donation Test Server (multi-streamer)")

EXPECTED_CALLBACK_SUFFIX = "/auth/chzzk/callback"


class StreamerCreateBody(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)


def _load_oauth_states() -> dict[str, dict[str, Any]]:
    if not STATE_FILE.exists():
        return {}
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if isinstance(raw, dict) and raw and all(isinstance(v, (int, float)) for v in raw.values()):
        return {k: {"created_at": float(v), "streamer_uid": ""} for k, v in raw.items()}
    if not isinstance(raw, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for state, meta in raw.items():
        if isinstance(meta, dict):
            result[state] = {
                "created_at": float(meta.get("created_at", 0)),
                "streamer_uid": str(meta.get("streamer_uid", "")),
            }
        elif isinstance(meta, (int, float)):
            result[state] = {"created_at": float(meta), "streamer_uid": ""}
    return result


def _save_oauth_states(states: dict[str, dict[str, Any]]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(states, ensure_ascii=False, indent=2), encoding="utf-8")


def _prune_oauth_states(states: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    now = time.time()
    return {
        k: v
        for k, v in states.items()
        if now - float(v.get("created_at", 0)) <= STATE_TTL_SEC
    }


def _register_oauth_state(state: str, streamer_uid: str) -> None:
    oauth_states.add(state)
    states = _prune_oauth_states(_load_oauth_states())
    states[state] = {"created_at": time.time(), "streamer_uid": streamer_uid}
    _save_oauth_states(states)


def _consume_oauth_state(state: str) -> str | None:
    states = _prune_oauth_states(_load_oauth_states())
    meta = states.pop(state, None)
    oauth_states.discard(state)
    _save_oauth_states(states)
    if not meta:
        return None
    uid = str(meta.get("streamer_uid", "")).strip()
    return uid or None


def _redirect_uri_ok() -> bool:
    return REDIRECT_URI.rstrip("/").endswith(EXPECTED_CALLBACK_SUFFIX)


streamer_store = StreamerStore(STREAMERS_DB)
donation_store = DonationStore(redis_url=REDIS_URL, sqlite_path=SQLITE_PATH)


def _on_channel_id(streamer_uid: str, channel_id: str) -> None:
    streamer_store.update_channel_id(streamer_uid, channel_id)


listener_manager = DonationListenerManager(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    streamer_store=streamer_store,
    donation_store=donation_store,
    refresh_tokens=refresh_access_token,
    on_channel_id=_on_channel_id,
)


@app.on_event("startup")
async def startup() -> None:
    migrated = streamer_store.import_legacy_tokens(TOKEN_FILE)
    if migrated:
        logger.info("레거시 tokens.json → streamer uid=%s 로 마이그레이션", migrated[:8])

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
    listener_manager.start_all()
    logger.info("후원 리스너 매니저 시작 (스트리머 %d명)", len(streamer_store.list_all()))


async def _handle_oauth_callback(
    code: str | None,
    state: str | None,
    error: str | None,
) -> RedirectResponse:
    if error:
        logger.error("OAuth provider error: %s", error)
        raise HTTPException(400, f"OAuth 실패: {error}")
    if not code or not state:
        raise HTTPException(400, "code 또는 state 가 없습니다.")
    streamer_uid = _consume_oauth_state(state)
    if not streamer_uid:
        raise HTTPException(400, "state 불일치 — /auth/chzzk?uid=... 부터 다시 시작하세요.")
    if not streamer_store.get(streamer_uid):
        raise HTTPException(400, f"스트리머 없음: {streamer_uid}")

    try:
        token_data = await exchange_code(CLIENT_ID, CLIENT_SECRET, code, state)
    except ChzzkApiError as exc:
        raise HTTPException(400, f"토큰 발급 실패: {exc}") from exc

    streamer_store.save_tokens(
        streamer_uid,
        {
            "access_token": token_data["accessToken"],
            "refresh_token": token_data["refreshToken"],
            "token_type": token_data.get("tokenType", "Bearer"),
            "expires_in": int(token_data.get("expiresIn", 86400)),
        },
    )
    logger.info("OAuth 완료 uid=%s — 리스너 연결", streamer_uid[:8])
    listener_manager.start(streamer_uid)
    return RedirectResponse(f"/?oauth=ok&uid={streamer_uid}")


def _index_html(streamers: list[dict[str, Any]], redirect_ok: bool, oauth_msg: str, oauth_uid: str) -> str:
    oauth_banner = ""
    if oauth_msg == "ok" and oauth_uid:
        oauth_banner = f'<p class="ok"><strong>OAuth 연결 완료!</strong> uid=<code>{oauth_uid}</code></p>'

    rows = ""
    for s in streamers:
        uid = s["streamer_uid"]
        auth = f'/auth/chzzk?uid={uid}'
        rows += f"""
        <tr>
          <td><code>{uid[:8]}…</code></td>
          <td>{s["display_name"]}</td>
          <td>{s["listener_status"]}</td>
          <td>{'✓' if s["has_token"] else '—'}</td>
          <td><a href="{auth}">OAuth</a></td>
          <td><a href="/donations?streamer_uid={uid}">후원</a></td>
        </tr>"""

    if not rows:
        rows = '<tr><td colspan="6">스트리머 없음 — POST /streamers 로 등록</td></tr>'

    return f"""
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <title>치지직 후원 테스트 (다중 스트리머)</title>
  <style>
    body {{ font-family: sans-serif; max-width: 960px; margin: 2rem auto; line-height: 1.6; }}
    code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 4px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    .ok {{ color: #0a7; }} .warn {{ color: #c80; }}
  </style>
</head>
<body>
  <h1>치지직 후원 API 테스트 (다중 스트리머)</h1>
  {oauth_banner}
  <p>Redirect URI: <code>{REDIRECT_URI}</code>
    <span class="{'ok' if redirect_ok else 'warn'}">{'OK' if redirect_ok else '경로 확인'}</span></p>
  <h2>스트리머</h2>
  <table>
    <tr><th>uid</th><th>이름</th><th>리스너</th><th>OAuth</th><th></th><th></th></tr>
    {rows}
  </table>
  <h2>등록</h2>
  <pre>curl -X POST {REDIRECT_URI.split('/auth')[0]}/streamers \\
  -H "Content-Type: application/json" \\
  -d '{{"display_name":"스트리머A"}}'</pre>
  <p><a href="/status">/status</a> · <a href="/streamers">/streamers</a> · <a href="/donations">/donations</a></p>
</body>
</html>
"""


@app.get("/")
async def index(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    oauth: str | None = None,
    uid: str | None = None,
):
    if code and state:
        return await _handle_oauth_callback(code, state, error)
    if error:
        raise HTTPException(400, f"OAuth 실패: {error}")
    return HTMLResponse(
        _index_html(listener_manager.statuses(), _redirect_uri_ok(), oauth or "", uid or "")
    )


@app.post("/streamers")
async def create_streamer(body: StreamerCreateBody) -> dict[str, Any]:
    streamer = streamer_store.create(body.display_name)
    listener_manager.start(streamer.uid)
    return {
        "streamer_uid": streamer.uid,
        "display_name": streamer.display_name,
        "oauth_url": f"/auth/chzzk?uid={streamer.uid}",
        "message": "OAuth URL로 스트리머 본인 계정 로그인",
    }


@app.get("/streamers")
async def list_streamers() -> dict[str, Any]:
    return {"count": len(listener_manager.statuses()), "streamers": listener_manager.statuses()}


@app.get("/streamers/{streamer_uid}")
async def get_streamer(streamer_uid: str) -> dict[str, Any]:
    streamer = streamer_store.get(streamer_uid)
    if not streamer:
        raise HTTPException(404, "스트리머 없음")
    status = next(
        (s for s in listener_manager.statuses() if s["streamer_uid"] == streamer_uid),
        None,
    )
    return {
        "streamer_uid": streamer.uid,
        "display_name": streamer.display_name,
        "chzzk_channel_id": streamer.chzzk_channel_id,
        "has_token": streamer.has_token,
        "listener": status,
        "oauth_url": f"/auth/chzzk?uid={streamer.uid}",
    }


@app.delete("/streamers/{streamer_uid}")
async def delete_streamer(streamer_uid: str) -> dict[str, str]:
    if not streamer_store.get(streamer_uid):
        raise HTTPException(404, "스트리머 없음")
    listener_manager.stop(streamer_uid)
    streamer_store.delete(streamer_uid)
    return {"message": f"삭제됨: {streamer_uid}"}


@app.get("/auth/chzzk")
async def auth_chzzk(uid: str = Query(..., description="POST /streamers 로 발급받은 uid")) -> RedirectResponse:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise HTTPException(500, "CHZZK_CLIENT_ID / CHZZK_CLIENT_SECRET 을 .env 에 설정하세요.")
    if not streamer_store.get(uid):
        raise HTTPException(404, f"스트리머 없음: {uid}")

    state = new_oauth_state()
    _register_oauth_state(state, uid)
    url = build_auth_url(CLIENT_ID, REDIRECT_URI, state)
    logger.info("OAuth 시작 uid=%s", uid[:8])
    return RedirectResponse(url)


@app.get("/auth/chzzk/callback")
async def auth_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    return await _handle_oauth_callback(code, state, error)


@app.get("/status")
async def status() -> dict[str, Any]:
    streamers = listener_manager.statuses()
    listening = sum(1 for s in streamers if s["listener_status"] == "listening")
    return {
        "streamer_count": len(streamers),
        "listening_count": listening,
        "streamers": streamers,
        "redirect_uri": REDIRECT_URI,
        "redirect_uri_ok": _redirect_uri_ok(),
        "storage": donation_store.stats(),
    }


@app.get("/donations")
async def donations(
    streamer_uid: str | None = Query(default=None),
    limit: int = Query(default=DONATION_LIST_LIMIT, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    if streamer_uid and not streamer_store.get(streamer_uid):
        raise HTTPException(404, "스트리머 없음")
    items = donation_store.sqlite.list_recent(
        limit=limit, offset=offset, streamer_uid=streamer_uid
    )
    return {
        "source": "sqlite",
        "streamer_uid": streamer_uid,
        "count": len(items),
        "total": donation_store.sqlite.count(streamer_uid=streamer_uid),
        "queue_pending": donation_store.queue.queue_length(),
        "donations": items,
    }


@app.get("/donations/recent")
async def donations_recent(
    streamer_uid: str | None = Query(default=None),
    limit: int = Query(default=DONATION_LIST_LIMIT, ge=1, le=200),
) -> dict[str, Any]:
    records = donation_store.queue.recent(limit=limit)
    if streamer_uid:
        records = [r for r in records if r.streamer_uid == streamer_uid]
    items = [
        {
            "streamer_uid": r.streamer_uid,
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
        "streamer_uid": streamer_uid,
        "count": len(items),
        "queue_pending": donation_store.queue.queue_length(),
        "donations": items,
    }


@app.post("/listener/restart")
async def restart_all_listeners() -> dict[str, str]:
    listener_manager.restart_all()
    donation_store.stop_worker()
    donation_store.start_worker()
    return {"message": "모든 리스너 + 큐 워커 재시작"}


@app.post("/streamers/{streamer_uid}/listener/restart")
async def restart_streamer_listener(streamer_uid: str) -> dict[str, str]:
    if not streamer_store.get(streamer_uid):
        raise HTTPException(404, "스트리머 없음")
    listener_manager.restart(streamer_uid)
    return {"message": f"리스너 재시작: {streamer_uid}"}


@app.post("/streamers/{streamer_uid}/auth/reset")
async def reset_streamer_auth(streamer_uid: str) -> dict[str, Any]:
    streamer = streamer_store.get(streamer_uid)
    if not streamer:
        raise HTTPException(404, "스트리머 없음")

    listener_manager.stop(streamer_uid)
    tokens = streamer_store.get_tokens(streamer_uid)
    revoked = False
    revoke_error: str | None = None
    sessions_before: Any = None

    if tokens and tokens.get("access_token") and CLIENT_ID and CLIENT_SECRET:
        try:
            sessions_before = list_user_sessions_sync(tokens["access_token"])
        except Exception as exc:
            logger.warning("세션 목록 조회 실패: %s", exc)
        try:
            revoke_token_sync(CLIENT_ID, CLIENT_SECRET, tokens["access_token"])
            revoked = True
        except Exception as exc:
            revoke_error = str(exc)

    streamer_store.clear_tokens(streamer_uid)
    listener_manager.start(streamer_uid)

    return {
        "message": f"OAuth 초기화 — /auth/chzzk?uid={streamer_uid} 로 다시 로그인",
        "streamer_uid": streamer_uid,
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
