"""공개 스트리머 랜딩 · connect."""

from __future__ import annotations

import html as html_module
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from portal.deps import PortalDeps
from portal.session_util import clear_streamer_session, get_streamer_uid, set_streamer_uid

router = APIRouter(tags=["public"])


def _deps(request: Request) -> PortalDeps:
    return request.app.state.deps


def _fmt_received_at(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return "—"
    if "T" in text:
        return text.replace("T", " ").split(".")[0][:19]
    return text[:19]


def _donations_table_rows(items: list[dict[str, Any]]) -> str:
    if not items:
        return '<tr><td colspan="4" class="empty">아직 후원이 없습니다.</td></tr>'
    rows = ""
    for item in items:
        rows += f"""
        <tr>
          <td>{html_module.escape(_fmt_received_at(str(item.get("received_at", ""))))}</td>
          <td>{html_module.escape(str(item.get("donator_nickname", "")))}</td>
          <td class="amount">{html_module.escape(str(item.get("pay_amount", "")))}원</td>
          <td>{html_module.escape(str(item.get("donation_text") or "—"))}</td>
        </tr>"""
    return rows


def _donations_panel_html(deps: PortalDeps, streamer_uid: str) -> str:
    streamer = deps.streamer_repo.get(streamer_uid)
    if not streamer or not streamer.has_token:
        return ""

    limit = min(deps.settings.shared.donation_list_limit, 50)
    items = deps.donation_repo.sqlite.list_recent(limit=limit, streamer_uid=streamer_uid)
    total = deps.donation_repo.sqlite.count(streamer_uid=streamer_uid)
    name = html_module.escape(streamer.display_name)

    return f"""
  <section class="card donations-card" id="my-donations" data-streamer-name="{name}">
    <h2>내 후원 목록</h2>
    <p class="hint" id="donations-meta"><strong>{name}</strong> 님 · 총 {total}건 · 최근 {len(items)}건 표시</p>
    <div class="table-wrap">
      <table class="donations-table">
        <thead>
          <tr><th>시간</th><th>후원자</th><th>금액</th><th>메시지</th></tr>
        </thead>
        <tbody id="donations-tbody">
          {_donations_table_rows(items)}
        </tbody>
      </table>
    </div>
    <p class="hint">10초마다 자동 새로고침 · 브라우저를 닫으면 세션이 사라집니다</p>
  </section>"""


def _streamer_landing_html(
    deps: PortalDeps, oauth_msg: str, session_uid: str, error: str = ""
) -> str:
    banner = ""
    reconnect = ""
    error_banner = ""
    if error == "consent":
        error_banner = """
  <div class="card" style="border-left:4px solid #c00">
    <p><strong>연결할 수 없습니다.</strong> 개인정보 수집·이용에 동의해 주세요.</p>
  </div>"""
    if oauth_msg == "ok" and session_uid:
        st = deps.streamer_service.bridge_streamer_status(session_uid)
        name = st["display_name"] if st else "스트리머"
        status = st["listener_status"] if st else "unknown"
        banner = f"""
  <div class="card ok">
    <h2>연결 완료</h2>
    <p><strong>{name}</strong> 님, 치지직 계정이 연결되었습니다.</p>
    <p>후원 수신 상태: <strong>{status}</strong></p>
    <p class="hint">이 브라우저 세션에서만 후원 목록이 보입니다. 브라우저를 닫으면 다시 연결해야 합니다.</p>
  </div>"""
    elif session_uid:
        st = deps.streamer_service.bridge_streamer_status(session_uid)
        if st:
            auth = f"/auth/chzzk?uid={session_uid}"
            reconnect = f"""
  <div class="card">
    <p><strong>{st["display_name"]}</strong> — 상태: {st["listener_status"]}</p>
    <p><a class="btn" href="{auth}">치지직 다시 연결</a></p>
  </div>"""

    donations_panel = _donations_panel_html(deps, session_uid) if session_uid else ""
    streamer = deps.streamer_repo.get(session_uid) if session_uid else None
    connected = bool(streamer and streamer.has_token)
    show_connect_form = not connected
    other_account_link = ""
    if connected:
        other_account_link = """
  <p class="hint" style="text-align:center">
    <form method="post" action="/logout" style="display:inline">
      <button type="submit" class="link-btn">다른 계정으로 연결하기</button>
    </form>
  </p>"""

    connect_form = ""
    if show_connect_form:
        connect_form = f"""
  <div class="card">
    <form method="post" action="/connect">
      <label for="display_name">치지직 닉네임 (표시 이름)</label>
      <input id="display_name" name="display_name" type="text" required maxlength="100"
             placeholder="예: 내방송닉네임" />
      <label for="mc_username" style="margin-top:0.75rem">마인크래프트 닉네임</label>
      <input id="mc_username" name="mc_username" type="text" maxlength="100"
             placeholder="서버 접속 닉네임 (비우면 위와 동일)" />
      <p class="hint" style="margin-top:0.75rem">후원 이벤트는 이 마크 닉네임으로 전달됩니다. 접속 중이어야 합니다.</p>

      <div class="consent-box">
        <h3>수집하는 정보</h3>
        <p class="hint" style="margin:0">마인크래프트 후원 연동을 위해 아래 정보를 수집·이용합니다.</p>
        <ul>
          <li><strong>치지직 표시 닉네임</strong> — 스트리머 식별·연동 관리</li>
          <li><strong>마인크래프트 닉네임</strong> — 후원 이벤트를 받을 인게임 캐릭터 지정</li>
          <li><strong>치지직 OAuth 인증 정보</strong> — 치지직 로그인 시 발급되는 토큰 (후원 수신)</li>
          <li><strong>치지직 채널 ID</strong> — 본인 채널 후원 구독</li>
          <li><strong>후원 내역</strong> — 후원자 닉네임, 금액, 메시지 (마크 서버 전달·기록)</li>
        </ul>
        <p class="hint">이용 목적: 치지직 후원을 마인크래프트 서버로 연동<br>
        보관: 연동 해제·삭제 시까지 (서버 DB에 저장)</p>
        <label class="consent-label" for="consent">
          <input id="consent" name="consent" type="checkbox" value="yes" required />
          <span>위 내용을 확인했으며, 개인정보 수집·이용에 동의합니다.</span>
        </label>
      </div>

      <p style="margin-top:1rem"><button id="connect-btn" class="btn" type="submit" disabled>치지직 연결하기</button></p>
    </form>
  </div>"""

    donations_script = ""
    if donations_panel:
        donations_script = """
    async function loadMyDonations() {
      const panel = document.getElementById('my-donations');
      if (!panel) return;
      try {
        const res = await fetch('/my/donations?limit=30');
        const data = await res.json();
        if (res.status === 401 || res.status === 403) return;
        if (!res.ok) return;
        const tbody = document.getElementById('donations-tbody');
        const meta = document.getElementById('donations-meta');
        if (!tbody) return;
        const items = data.donations || [];
        const name = data.display_name || panel.dataset.streamerName || '';
        if (items.length === 0) {
          tbody.innerHTML = '<tr><td colspan="4" class="empty">아직 후원이 없습니다.</td></tr>';
        } else {
          tbody.innerHTML = items.map((d) => {
            const t = (d.received_at || '').replace('T', ' ').split('.')[0].slice(0, 19);
            const msg = d.donation_text ? escapeHtml(d.donation_text) : '—';
            return '<tr><td>' + escapeHtml(t) + '</td><td>' + escapeHtml(d.donator_nickname || '')
              + '</td><td class="amount">' + escapeHtml(String(d.pay_amount || '')) + '원</td><td>' + msg + '</td></tr>';
          }).join('');
        }
        if (meta && data.total != null) {
          meta.innerHTML = '<strong>' + escapeHtml(name) + '</strong> 님 · 총 '
            + data.total + '건 · 최근 ' + items.length + '건 표시';
        }
      } catch (e) { /* ignore */ }
    }
    function escapeHtml(s) {
      return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }
    loadMyDonations();
    setInterval(loadMyDonations, 10000);
"""

    return f"""
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>치지직 후원 연동</title>
  <style>
    body {{ font-family: sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; }}
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
    .consent-box {{
      margin-top: 1rem; padding: 0.85rem 1rem; background: #fff;
      border: 1px solid #ddd; border-radius: 6px; font-size: 0.9rem;
    }}
    .consent-box h3 {{ margin: 0 0 0.5rem; font-size: 0.95rem; }}
    .consent-box ul {{ margin: 0.5rem 0 0.75rem; padding-left: 1.2rem; }}
    .consent-box li {{ margin: 0.25rem 0; }}
    .consent-label {{
      display: flex; gap: 0.5rem; align-items: flex-start;
      font-weight: 600; cursor: pointer; margin: 0;
    }}
    .consent-label input {{ margin-top: 0.2rem; flex-shrink: 0; }}
    .btn:disabled {{ opacity: 0.45; cursor: not-allowed; }}
    .donations-card h2 {{ margin: 0 0 0.5rem; font-size: 1.1rem; }}
    .table-wrap {{ overflow-x: auto; margin-top: 0.5rem; }}
    .donations-table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
    .donations-table th, .donations-table td {{
      border: 1px solid #ddd; padding: 0.45rem 0.5rem; text-align: left; vertical-align: top;
    }}
    .donations-table th {{ background: #eee; font-weight: 600; }}
    .donations-table td.amount {{ white-space: nowrap; }}
    .donations-table td.empty {{ text-align: center; color: #666; }}
    .link-btn {{
      background: none; border: none; padding: 0; color: #03c75a; font-size: 0.9rem;
      cursor: pointer; text-decoration: underline; font-family: inherit;
    }}
  </style>
</head>
<body>
  <h1>치지직 후원 연동</h1>
  <p>마인크래프트 서버와 연동하려면 치지직 계정을 연결하세요.</p>
  {error_banner}
  {banner}
  {reconnect}
  {donations_panel}
  {other_account_link}
  {connect_form}
  <ol class="hint">
    <li>동의 후 버튼 → 치지직 로그인</li>
    <li>로그인 시 <strong>후원 조회</strong> 권한 허용</li>
    <li>연동 후 이 페이지에서 <strong>내 후원 목록</strong> 확인</li>
  </ol>
  <script>
    const consent = document.getElementById('consent');
    const connectBtn = document.getElementById('connect-btn');
    if (consent && connectBtn) {{
      const sync = () => {{ connectBtn.disabled = !consent.checked; }};
      consent.addEventListener('change', sync);
      sync();
    }}
{donations_script}
  </script>
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
    connect_error: str | None = None,
):
    deps = _deps(request)
    if code and state:
        return await deps.oauth_service.handle_callback(request, code, state, error)
    if error:
        raise HTTPException(400, f"OAuth 실패: {error}")
    session_uid = get_streamer_uid(request, deps.streamer_repo)
    return HTMLResponse(
        _streamer_landing_html(deps, oauth or "", session_uid, connect_error or "")
    )


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    clear_streamer_session(request)
    return RedirectResponse("/", status_code=303)


@router.post("/connect")
async def streamer_connect(
    request: Request,
    display_name: str = Form(...),
    mc_username: str = Form(default=""),
    consent: str | None = Form(default=None),
) -> RedirectResponse:
    if consent != "yes":
        return RedirectResponse("/?connect_error=consent", status_code=303)
    deps = _deps(request)
    streamer = deps.streamer_service.connect_by_display_name(display_name, mc_username)
    set_streamer_uid(request, streamer.uid)
    return RedirectResponse(f"/auth/chzzk?uid={streamer.uid}", status_code=303)
