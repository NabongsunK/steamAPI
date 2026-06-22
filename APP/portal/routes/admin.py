"""admin · status."""

from __future__ import annotations

import html
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["admin"])


def _admin_html(deps, streamers: list[dict[str, Any]]) -> str:
    rows = ""
    for s in streamers:
        uid = s["streamer_uid"]
        auth = f'/auth/chzzk?uid={uid}'
        rows += f"""
        <tr>
          <td><code>{uid}</code></td>
          <td>{s["display_name"]}</td>
          <td>{s["listener_status"]}</td>
          <td>{'✓' if s["has_token"] else '—'}</td>
          <td><a href="{auth}">OAuth</a></td>
          <td><a href="/donations?streamer_uid={uid}">후원</a></td>
          <td>
            <button type="button" class="btn btn-warn btn-delete-streamer"
                    data-uid="{uid}" data-name="{html.escape(s['display_name'], quote=True)}">삭제</button>
          </td>
        </tr>"""

    if not rows:
        rows = '<tr><td colspan="7">등록된 스트리머 없음</td></tr>'

    redirect_uri = deps.settings.redirect_uri
    redirect_ok = deps.settings.redirect_uri_ok

    return f"""
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <title>관리 — 치지직 후원</title>
  <style>
    body {{ font-family: sans-serif; max-width: 1100px; margin: 2rem auto; line-height: 1.6; }}
    code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 4px; font-size: 0.85rem; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    .ok {{ color: #0a7; }} .warn {{ color: #c80; }}
    .log-panel {{ margin-top: 1.5rem; }}
    .log-toolbar {{ display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; margin-bottom: 0.5rem; }}
    .log-toolbar label {{ font-size: 0.9rem; }}
    #mc-log-meta {{ color: #666; font-size: 0.85rem; margin: 0; }}
    #mc-log-box {{
      background: #1e1e1e; color: #d4d4d4; padding: 0.75rem 1rem;
      border-radius: 6px; max-height: 420px; overflow: auto;
      font-family: ui-monospace, Consolas, monospace; font-size: 0.8rem;
      white-space: pre-wrap; word-break: break-all; margin: 0;
    }}
    button.btn {{ padding: 0.35rem 0.75rem; cursor: pointer; }}
    button.btn-warn {{ background: #fff3e0; border: 1px solid #e65100; color: #bf360c; border-radius: 4px; }}
    button.btn-warn:disabled {{ opacity: 0.45; cursor: not-allowed; }}
    button.btn-warn:not(:disabled):hover {{ background: #ffe0b2; }}
  </style>
</head>
<body>
  <h1>관리자 (개발용)</h1>
  <p><a href="/">← 스트리머 연동 페이지</a></p>
  <p>Redirect URI: <code>{redirect_uri}</code>
    <span class="{'ok' if redirect_ok else 'warn'}">{'OK' if redirect_ok else '확인 필요'}</span></p>
  <p>Bridge: <code>{deps.settings.bridge_url}</code></p>
  <table>
    <tr><th>uid</th><th>이름</th><th>리스너</th><th>OAuth</th><th></th><th>후원</th><th>삭제</th></tr>
    {rows}
  </table>
  <p><a href="/status">/status</a> · <a href="/streamers">/streamers</a> · <a href="/donations">/donations</a></p>

  <section class="log-panel">
    <h2>마크 서버 로그 (후원·NR-Donation)</h2>
    <p id="mc-log-meta">로딩 중…</p>
    <div class="log-toolbar">
      <button type="button" class="btn" id="mc-log-refresh">새로고침</button>
      <label><input type="checkbox" id="mc-log-all" /> 필터 없이 전체 tail</label>
      <label><input type="checkbox" id="mc-log-auto" checked /> 5초 자동 새로고침</label>
    </div>
    <pre id="mc-log-box">(로딩 중)</pre>
  </section>

  <script>
    document.querySelectorAll('.btn-delete-streamer').forEach((btn) => {{
      btn.addEventListener('click', async () => {{
        const uid = btn.dataset.uid;
        const name = btn.dataset.name || uid;
        if (!confirm('「' + name + '」 스트리머를 삭제할까요?\\nDB에서 완전히 지워지며, 다시 연동하면 새 uid가 생깁니다.')) {{
          return;
        }}
        btn.disabled = true;
        try {{
          const res = await fetch('/streamers/' + encodeURIComponent(uid), {{
            method: 'DELETE',
          }});
          const data = await res.json().catch(() => ({{}}));
          if (!res.ok) {{
            const detail = data.detail;
            const msg = typeof detail === 'string' ? detail : res.statusText || '요청 실패';
            throw new Error(msg);
          }}
          alert(data.message || '삭제되었습니다.');
          location.reload();
        }} catch (e) {{
          alert('삭제 실패: ' + e.message);
          btn.disabled = false;
        }}
      }});
    }});

    const box = document.getElementById('mc-log-box');
    const meta = document.getElementById('mc-log-meta');
    const refreshBtn = document.getElementById('mc-log-refresh');
    const allCheck = document.getElementById('mc-log-all');
    const autoCheck = document.getElementById('mc-log-auto');
    let timer = null;

    async function loadMcLogs() {{
      const all = allCheck.checked ? '1' : '0';
      try {{
        const res = await fetch('/admin/mc-logs?all=' + all);
        const data = await res.json();
        const count = data.line_count ?? 0;
        const filtered = data.filtered ? '후원 관련만' : '전체 tail';
        const status = data.exists ? filtered + ' · ' + count + '줄' : (data.message || '로그 없음');
        meta.textContent = status;
        if (!data.lines || data.lines.length === 0) {{
          box.textContent = data.message || '(표시할 로그 없음)';
        }} else {{
          box.textContent = data.lines.join('\\n');
          box.scrollTop = box.scrollHeight;
        }}
      }} catch (e) {{
        meta.textContent = '로그 로드 실패';
        box.textContent = String(e);
      }}
    }}

    function resetTimer() {{
      if (timer) clearInterval(timer);
      timer = null;
      if (autoCheck.checked) {{
        timer = setInterval(loadMcLogs, 5000);
      }}
    }}

    refreshBtn.addEventListener('click', loadMcLogs);
    allCheck.addEventListener('change', loadMcLogs);
    autoCheck.addEventListener('change', resetTimer);
    loadMcLogs();
    resetTimer();
  </script>
</body>
</html>
"""


@router.get("/admin")
async def admin_page(request: Request) -> HTMLResponse:
    deps = request.app.state.deps
    return HTMLResponse(_admin_html(deps, deps.streamer_service.bridge_statuses()))


@router.get("/admin/mc-logs")
async def admin_mc_logs(
    request: Request,
    all: bool = Query(default=False, description="true면 필터 없이 tail"),
) -> dict[str, Any]:
    return request.app.state.deps.mc_log_service.read_donation_logs(all_lines=all)


@router.get("/status")
async def status(request: Request) -> dict[str, Any]:
    deps = request.app.state.deps
    bridge_status = deps.bridge_client.get_status()
    if bridge_status:
        return {
            "portal": "ok",
            "bridge_url": deps.settings.bridge_url,
            "streamer_count": bridge_status.get("streamer_count", 0),
            "listening_count": bridge_status.get("listening_count", 0),
            "streamers": bridge_status.get("streamers", []),
            "redirect_uri": deps.settings.redirect_uri,
            "redirect_uri_ok": deps.settings.redirect_uri_ok,
            "storage": bridge_status.get("storage"),
            "forward_enabled": bridge_status.get("forward_enabled"),
        }
    return {
        "portal": "ok",
        "bridge_url": deps.settings.bridge_url,
        "bridge": "unreachable",
        "redirect_uri": deps.settings.redirect_uri,
        "redirect_uri_ok": deps.settings.redirect_uri_ok,
        "streamers": deps.streamer_service.bridge_statuses(),
    }


@router.post("/listener/restart")
async def restart_all_listeners(request: Request) -> dict[str, str]:
    request.app.state.deps.bridge_client.restart_all_listeners()
    return {"message": "bridge에 전체 리스너 재시작 요청"}
