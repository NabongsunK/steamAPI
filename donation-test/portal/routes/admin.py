"""admin · status."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["admin"])


def _admin_html(deps, streamers: list[dict[str, Any]]) -> str:
    rows = ""
    for s in streamers:
        uid = s["streamer_uid"]
        auth = f'/auth/chzzk?uid={uid}'
        reset = f'/streamers/{uid}/auth/reset'
        rows += f"""
        <tr>
          <td><code>{uid}</code></td>
          <td>{s["display_name"]}</td>
          <td>{s["listener_status"]}</td>
          <td>{'✓' if s["has_token"] else '—'}</td>
          <td><a href="{auth}">OAuth</a></td>
          <td><a href="/donations?streamer_uid={uid}">후원</a></td>
          <td><code>POST {reset}</code></td>
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
  </style>
</head>
<body>
  <h1>관리자 (개발용)</h1>
  <p><a href="/">← 스트리머 연동 페이지</a></p>
  <p>Redirect URI: <code>{redirect_uri}</code>
    <span class="{'ok' if redirect_ok else 'warn'}">{'OK' if redirect_ok else '확인 필요'}</span></p>
  <p>Bridge: <code>{deps.settings.bridge_url}</code></p>
  <table>
    <tr><th>uid</th><th>이름</th><th>리스너</th><th>OAuth</th><th></th><th>후원</th><th>초기화</th></tr>
    {rows}
  </table>
  <p><a href="/status">/status</a> · <a href="/streamers">/streamers</a> · <a href="/donations">/donations</a></p>
</body>
</html>
"""


@router.get("/admin")
async def admin_page(request: Request) -> HTMLResponse:
    deps = request.app.state.deps
    return HTMLResponse(_admin_html(deps, deps.streamer_service.bridge_statuses()))


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
