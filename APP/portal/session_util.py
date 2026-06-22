"""브라우저 세션(쿠키) — 탭/브라우저 종료 시 만료."""

from __future__ import annotations

from fastapi import Request

from shared.repos.streamer_repo import StreamerRepo

SESSION_STREAMER_KEY = "streamer_uid"


def get_streamer_uid(request: Request, repo: StreamerRepo) -> str:
    uid = str(request.session.get(SESSION_STREAMER_KEY) or "").strip()
    if not uid:
        return ""
    if not repo.get(uid):
        request.session.pop(SESSION_STREAMER_KEY, None)
        return ""
    return uid


def set_streamer_uid(request: Request, streamer_uid: str) -> None:
    request.session[SESSION_STREAMER_KEY] = streamer_uid.strip()


def clear_streamer_session(request: Request) -> None:
    request.session.clear()
