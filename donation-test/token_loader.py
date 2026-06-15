"""디버그 스크립트용 OAuth 토큰 로드 (다중 스트리머)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from shared.repos.streamer_repo import StreamerRepo

TOKEN_FILE = Path(os.getenv("TOKEN_FILE", "data/tokens.json"))
STREAMERS_DB = Path(os.getenv("STREAMERS_DB", "data/streamers.db"))


def load_access_token(streamer_uid: str | None = None) -> tuple[str, str]:
    """
    access_token과 streamer_uid 반환.
    우선순위: STREAMER_UID env → 인자 → streamers DB 첫 토큰 → legacy tokens.json
    """
    uid = streamer_uid or os.getenv("STREAMER_UID", "").strip()
    store = StreamerRepo(STREAMERS_DB)

    if uid:
        tokens = store.get_tokens(uid)
        if not tokens or not tokens.get("access_token"):
            raise SystemExit(f"스트리머 토큰 없음: {uid} — /auth/chzzk?uid={uid}")
        return tokens["access_token"], uid

    with_token = store.list_with_tokens()
    if with_token:
        tokens = store.get_tokens(with_token[0].uid)
        if tokens and tokens.get("access_token"):
            return tokens["access_token"], with_token[0].uid

    if TOKEN_FILE.exists():
        data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        token = data.get("access_token")
        if token:
            return token, "legacy-file"

    raise SystemExit(
        "토큰 없음 — POST /streamers 후 /auth/chzzk?uid=... 또는 data/tokens.json"
    )
