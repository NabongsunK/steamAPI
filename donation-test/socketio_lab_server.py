#!/usr/bin/env python3
"""
Socket.IO 에코 테스트 서버 (치지직 API 무관).

  cd donation-test
  pip install eventlet   # lab 서버용 (python-socketio 4.x + Python 3.13)
  python socketio_lab_server.py

다른 PC에서 접속:
  python socketio_lab_client.py http://100.73.52.88:8765

환경변수: SOCKETIO_LAB_HOST (기본 0.0.0.0), SOCKETIO_LAB_PORT (기본 8765)
"""

from __future__ import annotations

import logging
import os

import socketio

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HOST = os.getenv("SOCKETIO_LAB_HOST", "0.0.0.0")
PORT = int(os.getenv("SOCKETIO_LAB_PORT", "8765"))

# AsyncServer + uvicorn은 Python 3.13에서 python-socketio 4.6.x emit 버그 유발
sio = socketio.Server(cors_allowed_origins="*")
app = socketio.WSGIApp(sio)


@sio.event
def connect(sid, environ) -> None:
    addr = environ.get("REMOTE_ADDR", "?")
    logger.info("연결: sid=%s from=%s", sid, addr)


@sio.event
def disconnect(sid) -> None:
    logger.info("종료: sid=%s", sid)


@sio.on("ping_test")
def on_ping_test(sid, data) -> None:
    logger.info("ping_test: sid=%s data=%s", sid, data)
    sio.emit("pong_test", {"echo": data, "sid": sid}, room=sid)


def main() -> None:
    try:
        import eventlet
        import eventlet.wsgi
    except ImportError:
        raise SystemExit(
            "eventlet 필요: pip install eventlet\n"
            "(python-socketio 4.6 + Python 3.13 lab 서버용)"
        )

    logger.info("Socket.IO lab 서버 시작 — %s:%d (eventlet)", HOST, PORT)
    eventlet.wsgi.server(eventlet.listen((HOST, PORT)), app)


if __name__ == "__main__":
    main()
