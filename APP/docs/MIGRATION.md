# 아키텍처 · 마이그레이션

> AI/개발자용 단일 참조 문서. 구조 변경 시 이 파일을 먼저 갱신한다.

## 목표

기존 단일 `server.py`를 **두 프로세스**로 분리하고, 각 프로세스 안에서 **route → service → repo** 레이어를 유지한다.

| 프로세스   | 포트 | 역할                                                         | 공개                      |
| ---------- | ---- | ------------------------------------------------------------ | ------------------------- |
| **portal** | 3000 | 스트리머 온보딩, OAuth, admin API, 후원 조회                 | nginx → wwmw.shop         |
| **bridge** | 3001 | 치지직 WS 후원 수신, Redis/SQLite 저장, (예정) SteamAPI POST | `127.0.0.1` / Tailscale만 |

## 디렉터리 구조

```
APP/
├── docs/
│   └── MIGRATION.md          # 이 문서
├── shared/                   # 두 프로세스 공통
│   ├── config.py
│   ├── models/
│   │   └── events.py         # DonationEvent
│   ├── repos/
│   │   ├── streamer_repo.py
│   │   └── donation_repo.py
│   └── chzzk/
│       ├── api.py
│       └── ws.py
├── portal/
│   ├── main.py               # python -m portal.main
│   ├── config.py
│   ├── deps.py               # DI / 싱글톤
│   ├── routes/
│   │   ├── public.py
│   │   ├── oauth.py
│   │   ├── streamers.py
│   │   ├── donations.py
│   │   └── admin.py
│   └── services/
│       ├── oauth_service.py
│       ├── streamer_service.py
│       └── bridge_client.py  # bridge 내부 API 호출
├── bridge/
│   ├── main.py               # python -m bridge.main
│   ├── config.py
│   ├── deps.py
│   ├── routes/
│   │   └── internal.py       # /health, /internal/*
│   └── services/
│       ├── donation_listener.py
│       ├── ingestion_service.py
│       └── forward_service.py  # SteamAPI POST (스텁 → 구현 예정)
├── data/                     # 공유 SQLite (두 프로세스)
│   ├── streamers.db
│   └── donations.db
├── server.py                 # 호환: portal.main 래퍼 (python server.py)
```

## 레이어 규칙

| 레이어       | 책임                              | 금지                 |
| ------------ | --------------------------------- | -------------------- |
| **routes**   | HTTP 파싱, status code, Redirect  | DB/WS 직접 접근      |
| **services** | 비즈니스 로직, repo·외부 API 조합 | FastAPI Request 의존 |
| **repos**    | SQLite/Redis CRUD                 | HTTP/HTML            |

**shared**는 route를 갖지 않는다. repo·모델·chzzk 클라이언트만.

## 데이터 흐름

```
[스트리머] → portal:3000 (/connect → OAuth)
                ↓ save tokens
           streamers.db (shared)
                ↓ POST /internal/listeners/{uid}/start
           bridge:3001 (WS DONATION)
                ↓
           donations.db + Redis
                ↓ (예정)
           SteamAPI POST /events
```

## 프로세스 간 API (bridge internal)

| 메서드 | 경로                                | 호출 시점                          |
| ------ | ----------------------------------- | ---------------------------------- |
| `GET`  | `/health`                           | 헬스체크                           |
| `GET`  | `/internal/status`                  | portal `/status`, `/admin`         |
| `POST` | `/internal/listeners/{uid}/start`   | connect, OAuth 완료, streamer 생성 |
| `POST` | `/internal/listeners/{uid}/stop`    | streamer 삭제, auth reset          |
| `POST` | `/internal/listeners/{uid}/restart` | 수동 재시작                        |
| `POST` | `/internal/listeners/restart-all`   | 전체 재시작                        |

기본 `BRIDGE_URL=http://127.0.0.1:3001`

## 환경 변수

### 공통 (shared)

| 변수                  | 기본값                     |
| --------------------- | -------------------------- |
| `CHZZK_CLIENT_ID`     |                            |
| `CHZZK_CLIENT_SECRET` |                            |
| `STREAMERS_DB`        | `data/streamers.db`        |
| `REDIS_URL`           | `redis://127.0.0.1:6379/0` |
| `SQLITE_PATH`         | `data/donations.db`        |
| `TOKEN_FILE`          | `data/tokens.json`         |

### portal

| 변수                 | 기본값                                      |
| -------------------- | ------------------------------------------- |
| `PORT`               | `3000`                                      |
| `CHZZK_REDIRECT_URI` | `http://localhost:3000/auth/chzzk/callback` |
| `BRIDGE_URL`         | `http://127.0.0.1:3001`                     |
| `OAUTH_STATE_FILE`   | `data/oauth_states.json`                    |

### bridge

| 변수                     | 기본값                  |
| ------------------------ | ----------------------- |
| `BRIDGE_PORT`            | `3001`                  |
| `STEAM_API_URL`          | `http://127.0.0.1:4000` |
| `STEAM_API_SECRET`       |                         |
| `BRIDGE_FORWARD_ENABLED` | `false`                 |

## 실행 (맥미니)

```bash
cd ~/steamAPI/APP
source .venv/bin/activate

# 1) bridge 먼저
python -m bridge.main

# 2) 다른 터미널 — portal
python -m portal.main
```

nginx/cloudflared는 **portal:3000**만 프록시. bridge 3001은 로컬 바인딩.

## 마이그레이션 단계

- [x] **Phase 0** — `docs/MIGRATION.md` 작성
- [x] **Phase 1** — `shared/` (repos, chzzk, models, config)
- [x] **Phase 2** — `bridge/` (ingestion, internal API, main)
- [x] **Phase 3** — `portal/` (routes, services, main)
- [ ] **Phase 4** — `forward_service` SteamAPI 연동
- [x] **Phase 5** — 구 shim 파일 삭제, README 갱신
- [ ] **Phase 6** — 토큰 암호화 (`streamer_repo`)

## 호환성

- `python server.py` → `portal.main` 위임 (bridge는 별도 실행)

## 보안 메모

- `streamer_uid` (UUID): 암호화 불필요 (공개 식별자)
- `access_token` / `refresh_token`: Phase 6에서 암호화
- admin 경로: nginx 403 + Tailscale `macmini:3000`

## 관련 문서

- 루트 [README.md](../../README.md) — Bridge ↔ SteamAPI 전체 설계
- [APP/README.md](../README.md) — 실행·API 사용법
