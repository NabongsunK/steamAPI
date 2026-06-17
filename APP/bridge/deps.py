"""bridge 싱글톤 의존성."""

from __future__ import annotations

from dataclasses import dataclass

from shared.chzzk.api import refresh_access_token
from shared.repos.donation_repo import DonationRepo
from shared.repos.streamer_repo import StreamerRepo

from bridge.config import BridgeSettings
from bridge.services.forward_service import ForwardService
from bridge.services.ingestion_service import IngestionService


@dataclass
class BridgeDeps:
    settings: BridgeSettings
    streamer_repo: StreamerRepo
    donation_repo: DonationRepo
    forward_service: ForwardService
    ingestion: IngestionService


def build_deps(settings: BridgeSettings | None = None) -> BridgeDeps:
    settings = settings or BridgeSettings.from_env()
    shared = settings.shared

    streamer_repo = StreamerRepo(shared.streamers_db)
    donation_repo = DonationRepo(redis_url=shared.redis_url, sqlite_path=shared.sqlite_path)
    forward_service = ForwardService(
        api_url=settings.steam_api_url,
        api_secret=settings.steam_api_secret,
        enabled=settings.forward_enabled,
    )

    def on_channel_id(streamer_uid: str, channel_id: str) -> None:
        streamer_repo.update_channel_id(streamer_uid, channel_id)

    ingestion = IngestionService(
        client_id=shared.chzzk_client_id,
        client_secret=shared.chzzk_client_secret,
        streamer_repo=streamer_repo,
        donation_repo=donation_repo,
        refresh_tokens=refresh_access_token,
        on_channel_id=on_channel_id,
        on_donation=forward_service.on_donation,
    )

    return BridgeDeps(
        settings=settings,
        streamer_repo=streamer_repo,
        donation_repo=donation_repo,
        forward_service=forward_service,
        ingestion=ingestion,
    )
