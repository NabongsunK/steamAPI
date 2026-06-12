"""치지직 Open API (OAuth + Session) 클라이언트."""

from __future__ import annotations

import secrets
from typing import Any

import httpx

API_BASE = "https://openapi.chzzk.naver.com"
AUTH_PAGE = "https://chzzk.naver.com/account-interlock"


class ChzzkApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def _unwrap(payload: dict[str, Any]) -> Any:
    code = payload.get("code")
    if code != 200:
        raise ChzzkApiError(
            payload.get("message") or f"API error (code={code})",
            status_code=code if isinstance(code, int) else None,
            payload=payload,
        )
    return payload.get("content")


def build_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    from urllib.parse import urlencode

    query = urlencode(
        {
            "clientId": client_id,
            "redirectUri": redirect_uri,
            "state": state,
        }
    )
    return f"{AUTH_PAGE}?{query}"


def new_oauth_state() -> str:
    return secrets.token_urlsafe(16)


async def exchange_code(
    client_id: str,
    client_secret: str,
    code: str,
    state: str,
) -> dict[str, Any]:
    body = {
        "grantType": "authorization_code",
        "clientId": client_id,
        "clientSecret": client_secret,
        "code": code,
        "state": state,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{API_BASE}/auth/v1/token", json=body)
        resp.raise_for_status()
        return _unwrap(resp.json())


async def refresh_access_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> dict[str, Any]:
    body = {
        "grantType": "refresh_token",
        "clientId": client_id,
        "clientSecret": client_secret,
        "refreshToken": refresh_token,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{API_BASE}/auth/v1/token", json=body)
        resp.raise_for_status()
        return _unwrap(resp.json())


async def get_session_url(access_token: str) -> str:
    return get_session_url_sync(access_token)


def get_session_url_sync(access_token: str) -> str:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(f"{API_BASE}/open/v1/sessions/auth", headers=headers)
        resp.raise_for_status()
        content = _unwrap(resp.json())
        url = content.get("url")
        if not url:
            raise ChzzkApiError("세션 URL이 응답에 없습니다.", payload=content)
        return url


async def subscribe_donation(access_token: str, session_key: str) -> Any:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{API_BASE}/open/v1/sessions/events/subscribe/donation",
            headers=headers,
            params={"sessionKey": session_key},
        )
        resp.raise_for_status()
        return _unwrap(resp.json())


def subscribe_donation_sync(access_token: str, session_key: str) -> Any:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{API_BASE}/open/v1/sessions/events/subscribe/donation",
            headers=headers,
            params={"sessionKey": session_key},
        )
        resp.raise_for_status()
        return _unwrap(resp.json())
