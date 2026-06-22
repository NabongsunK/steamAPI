"""bridge 환경 설정."""

from __future__ import annotations

import os
from dataclasses import dataclass

from shared.config import SharedSettings


@dataclass(frozen=True)
class BridgeSettings:
    shared: SharedSettings
    port: int
    steam_api_url: str
    steam_api_secret: str
    forward_enabled: bool

    @classmethod
    def from_env(cls) -> BridgeSettings:
        return cls(
            shared=SharedSettings.from_env(),
            port=int(os.getenv("BRIDGE_PORT", "3001")),
            steam_api_url=os.getenv("STEAM_API_URL", "http://127.0.0.1:3000").rstrip("/"),
            steam_api_secret=os.getenv("STEAM_API_SECRET", ""),
            forward_enabled=os.getenv("BRIDGE_FORWARD_ENABLED", "false").lower() in ("1", "true", "yes"),
        )
