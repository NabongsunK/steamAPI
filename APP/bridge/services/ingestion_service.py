"""스트리머(uid)별 DonationListener 관리."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from bridge.services.donation_listener import DonationListener
from shared.models.events import DonationEvent
from shared.repos.donation_repo import DonationRepo
from shared.repos.streamer_repo import StreamerRepo

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        streamer_repo: StreamerRepo,
        donation_repo: DonationRepo,
        refresh_tokens: Callable[..., Any],
        on_channel_id: Callable[[str, str], None] | None = None,
        on_donation: Callable[[DonationEvent], None] | None = None,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.streamer_repo = streamer_repo
        self.donation_repo = donation_repo
        self.refresh_tokens = refresh_tokens
        self._on_channel_id = on_channel_id
        self._on_donation = on_donation
        self._listeners: dict[str, DonationListener] = {}
        self._lock = threading.Lock()

    def start_all(self) -> None:
        for streamer in self.streamer_repo.list_with_tokens():
            self.start(streamer.uid)
        for streamer in self.streamer_repo.list_all():
            if not streamer.has_token:
                self.start(streamer.uid)

    def start(self, streamer_uid: str) -> None:
        with self._lock:
            existing = self._listeners.get(streamer_uid)
            if existing and existing.status not in ("idle", "error") and self._thread_alive(existing):
                return
            if existing:
                existing.stop()
            listener = DonationListener(
                streamer_uid=streamer_uid,
                client_id=self.client_id,
                client_secret=self.client_secret,
                get_tokens=lambda uid=streamer_uid: self.streamer_repo.get_tokens(uid),
                save_tokens=lambda data, uid=streamer_uid: self.streamer_repo.save_tokens(uid, data),
                refresh_tokens=self.refresh_tokens,
                store=self.donation_repo,
                on_channel_id=self._on_channel_id,
                on_donation=self._on_donation,
            )
            self._listeners[streamer_uid] = listener
            listener.start()
            logger.info("리스너 시작: uid=%s", streamer_uid[:8])

    def stop(self, streamer_uid: str) -> None:
        with self._lock:
            listener = self._listeners.get(streamer_uid)
            if listener:
                listener.stop()

    def stop_all(self) -> None:
        with self._lock:
            for listener in self._listeners.values():
                listener.stop()

    def restart(self, streamer_uid: str) -> None:
        self.stop(streamer_uid)
        self.start(streamer_uid)

    def restart_all(self) -> None:
        self.stop_all()
        self.start_all()

    def get_listener(self, streamer_uid: str) -> DonationListener | None:
        return self._listeners.get(streamer_uid)

    def statuses(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for streamer in self.streamer_repo.list_all():
            listener = self._listeners.get(streamer.uid)
            result.append(
                {
                    "streamer_uid": streamer.uid,
                    "display_name": streamer.display_name,
                    "chzzk_channel_id": streamer.chzzk_channel_id,
                    "has_token": streamer.has_token,
                    "listener_status": listener.status if listener else "not_started",
                    "session_key": listener.session_key[:8] + "..." if listener and listener.session_key else None,
                    "last_error": listener.last_error if listener else None,
                }
            )
        return result

    @staticmethod
    def _thread_alive(listener: DonationListener) -> bool:
        thread = getattr(listener, "_thread", None)
        return thread is not None and thread.is_alive()
