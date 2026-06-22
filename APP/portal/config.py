"""portal 환경 설정."""

from __future__ import annotations

import os
from dataclasses import dataclass

from shared.config import SharedSettings


@dataclass(frozen=True)
class PortalSettings:
    shared: SharedSettings
    port: int
    redirect_uri: str
    bridge_url: str
    oauth_state_file: str
    oauth_state_ttl_sec: int
    steam_api_secret: str
    nr_donation_ws_url: str
    mc_log_path: str
    mc_log_scan_lines: int
    mc_log_max_lines: int

    @classmethod
    def from_env(cls) -> PortalSettings:
        return cls(
            shared=SharedSettings.from_env(),
            port=int(os.getenv("PORT", "3000")),
            redirect_uri=os.getenv("CHZZK_REDIRECT_URI", "http://localhost:3000/auth/chzzk/callback"),
            bridge_url=os.getenv("BRIDGE_URL", "http://127.0.0.1:3001").rstrip("/"),
            oauth_state_file=os.getenv("OAUTH_STATE_FILE", "data/oauth_states.json"),
            oauth_state_ttl_sec=int(os.getenv("OAUTH_STATE_TTL_SEC", "600")),
            steam_api_secret=os.getenv("STEAM_API_SECRET", ""),
            nr_donation_ws_url=os.getenv("NR_DONATION_WS_URL", "ws://127.0.0.1:8888"),
            mc_log_path=os.getenv(
                "MC_LOG_PATH",
                os.path.expanduser("~/minecraft-server/data/logs/latest.log"),
            ),
            mc_log_scan_lines=int(os.getenv("MC_LOG_SCAN_LINES", "2000")),
            mc_log_max_lines=int(os.getenv("MC_LOG_MAX_LINES", "80")),
        )

    @property
    def redirect_uri_ok(self) -> bool:
        return self.redirect_uri.rstrip("/").endswith("/auth/chzzk/callback")
