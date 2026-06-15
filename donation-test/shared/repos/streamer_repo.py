"""스트리머(uid) 등록·OAuth 토큰 저장."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Streamer:
    uid: str
    display_name: str
    chzzk_channel_id: str
    has_token: bool
    created_at: str


class StreamerRepo:
    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS streamers (
                    uid TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    chzzk_channel_id TEXT NOT NULL DEFAULT '',
                    access_token TEXT,
                    refresh_token TEXT,
                    token_type TEXT NOT NULL DEFAULT 'Bearer',
                    expires_in INTEGER,
                    oauth_at TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_streamers_channel ON streamers(chzzk_channel_id)"
            )
            conn.commit()

    def get_by_display_name(self, display_name: str) -> Streamer | None:
        name = display_name.strip()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT uid, display_name, chzzk_channel_id, created_at, access_token "
                "FROM streamers WHERE display_name = ?",
                (name,),
            ).fetchone()
        return self._row_to_streamer(row) if row else None

    def get_or_create(self, display_name: str) -> tuple[Streamer, bool]:
        """이름으로 조회, 없으면 생성. (streamer, created)"""
        existing = self.get_by_display_name(display_name)
        if existing:
            return existing, False
        return self.create(display_name), True

    def create(self, display_name: str) -> Streamer:
        name = display_name.strip()
        if not name:
            raise ValueError("display_name 필요")
        uid = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO streamers (uid, display_name) VALUES (?, ?)",
                (uid, name),
            )
            conn.commit()
            row = conn.execute(
                "SELECT uid, display_name, chzzk_channel_id, created_at, access_token "
                "FROM streamers WHERE uid = ?",
                (uid,),
            ).fetchone()
        return self._row_to_streamer(row)

    def get(self, uid: str) -> Streamer | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT uid, display_name, chzzk_channel_id, created_at, access_token "
                "FROM streamers WHERE uid = ?",
                (uid,),
            ).fetchone()
        return self._row_to_streamer(row) if row else None

    def list_all(self) -> list[Streamer]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT uid, display_name, chzzk_channel_id, created_at, access_token "
                "FROM streamers ORDER BY created_at ASC"
            ).fetchall()
        return [self._row_to_streamer(row) for row in rows]

    def list_with_tokens(self) -> list[Streamer]:
        return [s for s in self.list_all() if s.has_token]

    def save_tokens(self, uid: str, tokens: dict[str, Any]) -> None:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE streamers SET
                    access_token = ?,
                    refresh_token = ?,
                    token_type = ?,
                    expires_in = ?,
                    oauth_at = datetime('now')
                WHERE uid = ?
                """,
                (
                    tokens.get("access_token"),
                    tokens.get("refresh_token"),
                    tokens.get("token_type", "Bearer"),
                    int(tokens.get("expires_in", 86400)),
                    uid,
                ),
            )
            if cur.rowcount == 0:
                raise KeyError(f"streamer 없음: {uid}")
            conn.commit()

    def get_tokens(self, uid: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT access_token, refresh_token, token_type, expires_in
                FROM streamers WHERE uid = ?
                """,
                (uid,),
            ).fetchone()
        if not row or not row["access_token"]:
            return None
        return {
            "access_token": row["access_token"],
            "refresh_token": row["refresh_token"],
            "token_type": row["token_type"] or "Bearer",
            "expires_in": int(row["expires_in"] or 86400),
        }

    def clear_tokens(self, uid: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE streamers SET
                    access_token = NULL,
                    refresh_token = NULL,
                    expires_in = NULL,
                    oauth_at = NULL
                WHERE uid = ?
                """,
                (uid,),
            )
            conn.commit()

    def update_channel_id(self, uid: str, channel_id: str) -> None:
        if not channel_id:
            return
        with self._connect() as conn:
            conn.execute(
                "UPDATE streamers SET chzzk_channel_id = ? WHERE uid = ? AND chzzk_channel_id = ''",
                (channel_id, uid),
            )
            conn.commit()

    def delete(self, uid: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM streamers WHERE uid = ?", (uid,))
            conn.commit()
            return cur.rowcount > 0

    def import_legacy_tokens(self, token_file: Path, display_name: str = "legacy") -> str | None:
        """data/tokens.json → streamers DB (최초 1회)."""
        if not token_file.exists():
            return None
        if self.list_with_tokens():
            return None
        try:
            data = json.loads(token_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if not data.get("access_token"):
            return None
        streamer = self.create(display_name)
        self.save_tokens(
            streamer.uid,
            {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "token_type": data.get("token_type", "Bearer"),
                "expires_in": int(data.get("expires_in", 86400)),
            },
        )
        return streamer.uid

    @staticmethod
    def _row_to_streamer(row: sqlite3.Row) -> Streamer:
        return Streamer(
            uid=row["uid"],
            display_name=row["display_name"],
            chzzk_channel_id=row["chzzk_channel_id"] or "",
            has_token=bool(row["access_token"]),
            created_at=row["created_at"],
        )
