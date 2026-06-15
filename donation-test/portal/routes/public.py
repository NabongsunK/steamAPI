"""공개 스트리머 랜딩 · connect."""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from portal.deps import PortalDeps

router = APIRouter(tags=["public"])


def _deps(request: Request) -> PortalDeps:
    return request.app.state.deps


def _streamer_landing_html(deps: PortalDeps, oauth_msg: str, oauth_uid: str) -> str:
    banner = ""
    reconnect = ""
    if oauth_msg == "ok" and oauth_uid:
        st = deps.streamer_service.bridge_streamer_status(oauth_uid)
        name = st["display_name"] if st else "스트리머"
        status = st["listener_status"] if st else "unknown"
        banner = f"""
  <div class="card ok">
    <h2>연결 완료</h2>
    <p><strong>{name}</strong> 님, 치지직 계정이 연결되었습니다.</p>
    <p>후원 수신 상태: <strong>{status}</strong></p>
    <p class="hint">이 페이지를 북마크해 두시면 같은 이름으로 다시 연결할 수 있습니다.</p>
  </div>"""
    elif oauth_uid:
        st = deps.streamer_service.bridge_streamer_status(oauth_uid)
        if st:
            auth = f"/auth/chzzk?uid={oauth_uid}"
            reconnect = f"""
  <div class="card">
    <p><strong>{st["display_name"]}</strong> — 상태: {st["listener_status"]}</p>
    <p><a class="btn" href="{auth}">치지직 다시 연결</a></p>
  </div>"""

    return f"""
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>치지직 후원 연동</title>
  <style>
    body {{ font-family: sans-serif; max-width: 480px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; }}
    h1 {{ font-size: 1.35rem; }}
    .card {{ background: #f8f9fa; border-radius: 8px; padding: 1rem 1.25rem; margin: 1rem 0; }}
    .ok {{ border-left: 4px solid #0a7; }}
    label {{ display: block; margin-bottom: 0.35rem; font-weight: 600; }}
    input[type=text] {{ width: 100%; padding: 0.6rem; font-size: 1rem; box-sizing: border-box; }}
    .btn {{ display: inline-block; background: #03c75a; color: #fff; padding: 0.65rem 1.2rem;
            border-radius: 6px; text-decoration: none; font-weight: 600; border: none; cursor: pointer;
            font-size: 1rem; }}
    .hint {{ color: #666; font-size: 0.9rem; }}
    ol {{ padding-left: 1.2rem; }}
  </style>
</head>
<body>
  <h1>치지직 후원 연동</h1>
  <p>마인크래프트 서버와 연동하려면 치지직 계정을 연결하세요.</p>
  {banner}
  {reconnect}
  <div class="card">
    <form method="post" action="/connect">
      <label for="display_name">치지직 닉네임 (표시 이름)</label>
      <input id="display_name" name="display_name" type="text" required maxlength="100"
             placeholder="예: 내방송닉네임" />
      <p class="hint" style="margin-top:0.75rem">처음이면 등록되고, 같은 이름이면 기존 연결을 이어갑니다.</p>
      <p style="margin-top:1rem"><button class="btn" type="submit">치지직 연결하기</button></p>
    </form>
  </div>
  <ol class="hint">
    <li>위 버튼 → 치지직 로그인</li>
    <li>로그인 시 <strong>후원 조회</strong> 권한 허용</li>
    <li>본인 채널로 들어오는 후원이 연동됩니다</li>
  </ol>
</body>
</html>
"""


@router.get("/")
async def index(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    oauth: str | None = None,
    uid: str | None = None,
):
    deps = _deps(request)
    if code and state:
        return await deps.oauth_service.handle_callback(code, state, error)
    if error:
        raise HTTPException(400, f"OAuth 실패: {error}")
    return HTMLResponse(_streamer_landing_html(deps, oauth or "", uid or ""))


@router.post("/connect")
async def streamer_connect(request: Request, display_name: str = Form(...)) -> RedirectResponse:
    deps = _deps(request)
    streamer = deps.streamer_service.connect_by_display_name(display_name)
    return RedirectResponse(f"/auth/chzzk?uid={streamer.uid}", status_code=303)
