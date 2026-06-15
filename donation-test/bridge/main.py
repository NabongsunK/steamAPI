"""bridge 진입점 — python -m bridge.main"""

from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI

from bridge.config import BridgeSettings
from bridge.deps import BridgeDeps, build_deps
from bridge.routes import internal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bridge")


def create_app(deps: BridgeDeps | None = None) -> FastAPI:
    deps = deps or build_deps()
    app = FastAPI(title="Chzzk Bridge", docs_url=None, redoc_url=None)
    app.state.deps = deps
    app.include_router(internal.router)

    @app.on_event("startup")
    async def startup() -> None:
        migrated = deps.streamer_repo.import_legacy_tokens(deps.settings.shared.token_file)
        if migrated:
            logger.info("레거시 tokens.json → streamer uid=%s", migrated[:8])
        try:
            deps.donation_repo.queue.ping()
            deps.donation_repo.start_worker()
            logger.info("Redis OK · 큐 워커 시작")
        except Exception as exc:
            logger.error("Redis 연결 실패: %s", exc)
        deps.ingestion.start_all()
        logger.info(
            "bridge 기동 (port=%s, forward=%s, streamers=%d)",
            deps.settings.port,
            deps.forward_service.enabled,
            len(deps.streamer_repo.list_all()),
        )

    return app


def main() -> None:
    settings = BridgeSettings.from_env()
    if not settings.shared.chzzk_client_id:
        logger.warning("CHZZK_CLIENT_ID 미설정")
    app = create_app(build_deps(settings))
    uvicorn.run(app, host="127.0.0.1", port=settings.port, reload=False)


if __name__ == "__main__":
    main()
