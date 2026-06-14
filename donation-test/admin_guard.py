"""관리 API: Tailscale 직접 접속 또는 Admin API Key."""

from __future__ import annotations

import ipaddress
import os
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

# Tailscale CGNAT (100.64.0.0/10)
TAILSCALE_NET = ipaddress.ip_network("100.64.0.0/10")

ADMIN_TAILSCALE_ONLY = os.getenv("ADMIN_TAILSCALE_ONLY", "true").lower() in (
    "1",
    "true",
    "yes",
)
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "").strip()

# 쉼표 구분 IP 또는 CIDR. 설정 시 이 목록(+ localhost)만 관리 API 허용
# 예: ADMIN_ALLOWED_IPS=100.79.16.93,100.73.52.88
_ADMIN_ALLOWED_RAW = os.getenv("ADMIN_ALLOWED_IPS", "").strip()


def _parse_allowed_networks(raw: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            if "/" in token:
                nets.append(ipaddress.ip_network(token, strict=False))
            else:
                nets.append(ipaddress.ip_network(f"{token}/32", strict=False))
        except ValueError:
            continue
    return nets


ADMIN_ALLOWED_NETWORKS = _parse_allowed_networks(_ADMIN_ALLOWED_RAW)


def is_ip_allowed(ip: str) -> bool:
    if not ADMIN_ALLOWED_NETWORKS:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in ADMIN_ALLOWED_NETWORKS)


def _peer_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return ""


def is_tailscale_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in TAILSCALE_NET
    except ValueError:
        return False


def is_via_cloudflare(request: Request) -> bool:
    return bool(
        request.headers.get("cf-ray")
        or request.headers.get("cf-connecting-ip")
        or request.headers.get("CF-Connecting-IP")
    )


def has_valid_admin_key(request: Request) -> bool:
    if not ADMIN_API_KEY:
        return False
    header_key = request.headers.get("x-admin-key", "")
    query_key = request.query_params.get("admin_key", "")
    return header_key == ADMIN_API_KEY or query_key == ADMIN_API_KEY


def is_admin_request_allowed(request: Request) -> bool:
    if not ADMIN_TAILSCALE_ONLY:
        return True
    if has_valid_admin_key(request):
        return True

    peer = _peer_ip(request)
    via_cf = is_via_cloudflare(request)

    # 특정 IP 화이트리스트 — 목록에 있는 IP만 (127.0.0.1 자동 허용 없음)
    if ADMIN_ALLOWED_NETWORKS:
        if via_cf:
            return False
        return is_ip_allowed(peer)

    # 맥미니 로컬 (터널·CF 없음)
    if peer in ("127.0.0.1", "::1") and not via_cf:
        return True

    # Tailscale IP로 직접 접속 (100.73.52.88:3000 등) — CF 헤더 없음
    if is_tailscale_ip(peer) and not via_cf:
        return True

    return False


def needs_admin_protection(path: str, method: str, query: Any) -> bool:
    if path.startswith("/admin"):
        return True
    if path == "/status":
        return True
    if path.startswith("/streamers"):
        return True
    if path == "/listener/restart" and method == "POST":
        return True
    if path.startswith("/donations") and not query.get("streamer_uid"):
        return True
    return False


def admin_denied_response(request: Request) -> JSONResponse:
    peer = _peer_ip(request)
    via_cf = is_via_cloudflare(request)
    return JSONResponse(
        status_code=403,
        content={
            "detail": "관리 API — 허용된 IP에서 직접 접속하거나 X-Admin-Key 필요",
            "hint": "Tailscale: http://100.73.52.88:3000/admin · .env ADMIN_ALLOWED_IPS 확인",
            "peer": peer,
            "via_cloudflare": via_cf,
        },
    )
