"""portal 진입점 — python -m portal.main"""

from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI

from portal.config import PortalSettings
from portal.deps import PortalDeps, build_deps
from portal.routes import admin, donations, oauth, public, streamers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("portal")


def create_app(deps: PortalDeps | None = None) -> FastAPI:
    deps = deps or build_deps()
    app = FastAPI(title="Chzzk Donation Portal (multi-streamer)")
    app.state.deps = deps

    app.include_router(public.router)
    app.include_router(oauth.router)
    app.include_router(streamers.router)
    app.include_router(donations.router)
    app.include_router(admin.router)

    @app.on_event("startup")
    async def startup() -> None:
        migrated = deps.streamer_repo.import_legacy_tokens(deps.settings.shared.token_file)
        if migrated:
            logger.info("레거시 tokens.json → streamer uid=%s", migrated[:8])
        if not deps.settings.redirect_uri_ok:
            logger.warning(
                "CHZZK_REDIRECT_URI 확인 필요 (현재: %s)",
                deps.settings.redirect_uri,
            )
        logger.info(
            "portal 기동 (port=%s, bridge=%s)",
            deps.settings.port,
            deps.settings.bridge_url,
        )

    return app


def main() -> None:
    settings = PortalSettings.from_env()
    shared = settings.shared
    if not shared.chzzk_client_id or not shared.chzzk_client_secret:
        logger.warning(".env 파일에 CHZZK_CLIENT_ID, CHZZK_CLIENT_SECRET 을 넣어주세요.")
    app = create_app(build_deps(settings))
    uvicorn.run(app, host="0.0.0.0", port=settings.port, reload=False)


if __name__ == "__main__":
    main()
