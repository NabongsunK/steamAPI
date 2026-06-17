"""공통 환경 설정."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class SharedSettings:
    chzzk_client_id: str
    chzzk_client_secret: str
    streamers_db: Path
    redis_url: str
    sqlite_path: Path
    token_file: Path
    donation_list_limit: int

    @classmethod
    def from_env(cls) -> SharedSettings:
        return cls(
            chzzk_client_id=os.getenv("CHZZK_CLIENT_ID", ""),
            chzzk_client_secret=os.getenv("CHZZK_CLIENT_SECRET", ""),
            streamers_db=Path(os.getenv("STREAMERS_DB", "data/streamers.db")),
            redis_url=os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
            sqlite_path=Path(os.getenv("SQLITE_PATH", "data/donations.db")),
            token_file=Path(os.getenv("TOKEN_FILE", "data/tokens.json")),
            donation_list_limit=int(os.getenv("DONATION_LIST_LIMIT", "50")),
        )
