"""portal 싱글톤 의존성."""

from __future__ import annotations

from dataclasses import dataclass

from shared.repos.donation_repo import DonationRepo
from shared.repos.streamer_repo import StreamerRepo

from portal.config import PortalSettings
from portal.services.bridge_client import BridgeClient
from portal.services.oauth_service import OAuthService
from portal.services.streamer_service import StreamerService


@dataclass
class PortalDeps:
    settings: PortalSettings
    streamer_repo: StreamerRepo
    donation_repo: DonationRepo
    bridge_client: BridgeClient
    oauth_service: OAuthService
    streamer_service: StreamerService


def build_deps(settings: PortalSettings | None = None) -> PortalDeps:
    settings = settings or PortalSettings.from_env()
    shared = settings.shared

    streamer_repo = StreamerRepo(shared.streamers_db)
    donation_repo = DonationRepo(redis_url=shared.redis_url, sqlite_path=shared.sqlite_path)
    bridge_client = BridgeClient(settings.bridge_url)

    oauth_service = OAuthService(
        settings=settings,
        streamer_repo=streamer_repo,
        bridge_client=bridge_client,
    )
    streamer_service = StreamerService(
        settings=settings,
        streamer_repo=streamer_repo,
        bridge_client=bridge_client,
    )

    return PortalDeps(
        settings=settings,
        streamer_repo=streamer_repo,
        donation_repo=donation_repo,
        bridge_client=bridge_client,
        oauth_service=oauth_service,
        streamer_service=streamer_service,
    )
