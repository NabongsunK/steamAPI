"""후원 이벤트: Redis 큐 적재 → 워커가 SQLite에 영구 저장."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import redis

logger = logging.getLogger(__name__)

QUEUE_KEY = "donations:queue"
RECENT_KEY = "donations:recent"
DEFAULT_RECENT_SIZE = 50


@dataclass
class DonationRecord:
    received_at: str
    donator_nickname: str
    pay_amount: str
    donation_text: str
    donation_type: str
    channel_id: str
    donator_channel_id: str
    raw: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, payload: str) -> DonationRecord:
        data = json.loads(payload)
        return cls(
            received_at=data["received_at"],
            donator_nickname=data["donator_nickname"],
            pay_amount=data["pay_amount"],
            donation_text=data.get("donation_text", ""),
            donation_type=data.get("donation_type", ""),
            channel_id=data.get("channel_id", ""),
            donator_channel_id=data.get("donator_channel_id", ""),
            raw=data.get("raw", {}),
        )

    def to_row(self) -> dict[str, Any]:
        return {
            "received_at": self.received_at,
            "donator_nickname": self.donator_nickname,
            "pay_amount": self.pay_amount,
            "donation_text": self.donation_text,
            "donation_type": self.donation_type,
            "channel_id": self.channel_id,
            "donator_channel_id": self.donator_channel_id,
            "raw_json": json.dumps(self.raw, ensure_ascii=False),
        }


class RedisDonationQueue:
    def __init__(self, redis_url: str, recent_size: int = DEFAULT_RECENT_SIZE):
        self._client = redis.from_url(redis_url, decode_responses=True)
        self._recent_size = recent_size

    def ping(self) -> bool:
        return bool(self._client.ping())

    def enqueue(self, record: DonationRecord) -> None:
        payload = record.to_json()
        pipe = self._client.pipeline()
        pipe.rpush(QUEUE_KEY, payload)
        pipe.lpush(RECENT_KEY, payload)
        pipe.ltrim(RECENT_KEY, 0, self._recent_size - 1)
        pipe.execute()
        logger.debug("Redis 큐 적재: %s", record.donator_nickname)

    def dequeue_blocking(self, timeout_sec: int = 1) -> DonationRecord | None:
        item = self._client.blpop(QUEUE_KEY, timeout=timeout_sec)
        if not item:
            return None
        _, payload = item
        return DonationRecord.from_json(payload)

    def queue_length(self) -> int:
        return int(self._client.llen(QUEUE_KEY))

    def recent(self, limit: int = DEFAULT_RECENT_SIZE) -> list[DonationRecord]:
        items = self._client.lrange(RECENT_KEY, 0, max(0, limit - 1))
        return [DonationRecord.from_json(item) for item in items]


class SQLiteDonationStore:
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
                CREATE TABLE IF NOT EXISTS donations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    received_at TEXT NOT NULL,
                    donator_nickname TEXT NOT NULL,
                    pay_amount TEXT NOT NULL,
                    donation_text TEXT NOT NULL DEFAULT '',
                    donation_type TEXT NOT NULL DEFAULT '',
                    channel_id TEXT NOT NULL DEFAULT '',
                    donator_channel_id TEXT NOT NULL DEFAULT '',
                    raw_json TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_donations_received_at ON donations(received_at DESC)"
            )
            conn.commit()

    def insert(self, record: DonationRecord) -> int:
        row = record.to_row()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO donations (
                    received_at, donator_nickname, pay_amount, donation_text,
                    donation_type, channel_id, donator_channel_id, raw_json
                ) VALUES (
                    :received_at, :donator_nickname, :pay_amount, :donation_text,
                    :donation_type, :channel_id, :donator_channel_id, :raw_json
                )
                """,
                row,
            )
            conn.commit()
            return int(cur.lastrowid)

    def list_recent(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, received_at, donator_nickname, pay_amount, donation_text,
                       donation_type, channel_id, donator_channel_id, created_at
                FROM donations
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM donations").fetchone()
        return int(row["cnt"]) if row else 0


class DonationConsumer:
    """Redis 큐에서 꺼내 SQLite에 저장하는 백그라운드 워커."""

    def __init__(self, queue: RedisDonationQueue, store: SQLiteDonationStore):
        self._queue = queue
        self._store = store
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._processed = 0
        self._last_error: str | None = None

    @property
    def processed_count(self) -> int:
        return self._processed

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="donation-consumer", daemon=True)
        self._thread.start()
        logger.info("후원 큐 워커 시작 (Redis → SQLite)")

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                record = self._queue.dequeue_blocking(timeout_sec=1)
                if record is None:
                    continue
                donation_id = self._store.insert(record)
                self._processed += 1
                self._last_error = None
                logger.info(
                    "SQLite 저장 #%s: %s / %s원",
                    donation_id,
                    record.donator_nickname,
                    record.pay_amount,
                )
            except Exception as exc:
                self._last_error = str(exc)
                logger.exception("큐 처리 오류: %s", exc)


class DonationStore:
    """리스너·API가 사용하는 통합 저장소."""

    def __init__(
        self,
        redis_url: str,
        sqlite_path: Path,
        recent_size: int = DEFAULT_RECENT_SIZE,
    ):
        self.queue = RedisDonationQueue(redis_url, recent_size=recent_size)
        self.sqlite = SQLiteDonationStore(sqlite_path)
        self.consumer = DonationConsumer(self.queue, self.sqlite)

    def enqueue(self, record: DonationRecord) -> None:
        self.queue.enqueue(record)

    def start_worker(self) -> None:
        self.consumer.start()

    def stop_worker(self) -> None:
        self.consumer.stop()

    def stats(self) -> dict[str, Any]:
        return {
            "redis_connected": self.queue.ping(),
            "queue_pending": self.queue.queue_length(),
            "sqlite_total": self.sqlite.count(),
            "worker_running": self.consumer.running,
            "worker_processed": self.consumer.processed_count,
            "worker_last_error": self.consumer.last_error,
        }


def donation_record_from_event(event: Any) -> DonationRecord:
    """DonationEvent → DonationRecord."""
    return DonationRecord(
        received_at=event.received_at,
        donator_nickname=event.donator_nickname,
        pay_amount=event.pay_amount,
        donation_text=event.donation_text,
        donation_type=event.donation_type,
        channel_id=event.channel_id,
        donator_channel_id=event.donator_channel_id,
        raw=event.raw,
    )


def donation_record_now(payload: dict[str, Any]) -> DonationRecord:
    return DonationRecord(
        received_at=datetime.now(timezone.utc).isoformat(),
        donator_nickname=str(payload.get("donatorNickname", "")),
        pay_amount=str(payload.get("payAmount", "")),
        donation_text=str(payload.get("donationText", "")),
        donation_type=str(payload.get("donationType", "")),
        channel_id=str(payload.get("channelId", "")),
        donator_channel_id=str(payload.get("donatorChannelId", "")),
        raw=payload,
    )
