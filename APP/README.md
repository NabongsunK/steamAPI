# 치지직 후원 API 테스트 서버

치지직 Open API **Session WebSocket**으로 후원(`DONATION`) 이벤트를 받아 보는 Python 테스트 앱입니다.  
**portal**(온보딩·OAuth)과 **bridge**(후원 수신) 두 프로세스로 구성됩니다.

**관련 문서**

- [아키텍처 · 마이그레이션](docs/MIGRATION.md)
- [Session API](https://chzzk.gitbook.io/chzzk/chzzk-api/session)
- [Authorization (OAuth)](https://chzzk.gitbook.io/chzzk/chzzk-api/authorization)

---

## 사전 준비

1. [치지직 Open API](https://chzzk.gitbook.io/chzzk) 앱 등록 — Client ID / Secret
2. Redirect URI: `.env`의 `CHZZK_REDIRECT_URI`와 **완전히 동일** (예: `https://wwmw.shop/auth/chzzk/callback`)
3. Scope **후원 조회** 체크
4. **Redis** 로컬 실행 (`redis-cli ping` → `PONG`)

> 후원 WebSocket은 **스트리머 본인 OAuth**가 필요합니다.

---

## 설치

```bash
cd donation-test
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

---

## 환경 변수

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `CHZZK_CLIENT_ID` | 앱 Client ID | |
| `CHZZK_CLIENT_SECRET` | 앱 Client Secret | |
| `CHZZK_REDIRECT_URI` | OAuth 콜백 | `http://localhost:3000/auth/chzzk/callback` |
| `PORT` | portal 포트 | `3000` |
| `BRIDGE_URL` | bridge 내부 URL | `http://127.0.0.1:3001` |
| `BRIDGE_PORT` | bridge 포트 | `3001` |
| `STREAMERS_DB` | 스트리머·토큰 DB | `data/streamers.db` |
| `REDIS_URL` | Redis | `redis://127.0.0.1:6379/0` |
| `SQLITE_PATH` | 후원 SQLite | `data/donations.db` |

---

## 실행

**두 프로세스 모두** 켜야 후원 수신이 됩니다.

```bash
# 터미널 1 — bridge (WS · Redis 워커)
python -m bridge.main

# 터미널 2 — portal (OAuth · admin)
python -m portal.main
```

호환: `python server.py` → portal만 기동 (bridge는 별도 실행 필요)

- 스트리머: [http://localhost:3000](http://localhost:3000)
- 관리: [http://localhost:3000/admin](http://localhost:3000/admin)
- bridge 헬스: `http://127.0.0.1:3001/health` (로컬만)

---

## 사용 방법

### 1. 스트리머 연결

1. `/` 접속 → 닉네임 입력 → 치지직 OAuth
2. 토큰은 `data/streamers.db`에 저장
3. portal이 bridge에 리스너 시작 요청

### 2. 후원 확인

- bridge 터미널: `후원 수신` 로그
- [http://localhost:3000/donations](http://localhost:3000/donations) — SQLite
- [http://localhost:3000/donations/recent](http://localhost:3000/donations/recent) — Redis

### 3. 상태

[http://localhost:3000/status](http://localhost:3000/status) — bridge 연동·리스너·저장소 상태

리스너 전체 재시작:

```bash
curl -X POST http://localhost:3000/listener/restart
```

---

## HTTP API (portal)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/` | 스트리머 랜딩 |
| `POST` | `/connect` | 닉네임 등록 → OAuth |
| `GET` | `/auth/chzzk?uid=` | OAuth 시작 |
| `GET` | `/admin` | 관리 페이지 |
| `GET` | `/status` | 상태 JSON |
| `GET` | `/streamers` | 스트리머 목록 |
| `GET` | `/donations` | SQLite 후원 목록 |
| `POST` | `/listener/restart` | bridge 리스너 재시작 요청 |

---

## 파일 구조

```
donation-test/
├── docs/MIGRATION.md
├── shared/          # repos, chzzk 클라이언트, 모델
├── portal/          # OAuth · admin (:3000)
├── bridge/          # WS 수신 · Redis/SQLite (:3001)
├── server.py        # portal 호환 래퍼
├── debug_chzzk.py
└── data/
    ├── streamers.db
    └── donations.db
```

---

## 자주 나는 문제

### `listener_status: bridge_unreachable`

- **bridge가 안 떠 있음** → `python -m bridge.main` 먼저 실행
- `.env`의 `BRIDGE_URL` 확인

### `waiting_for_oauth`

- OAuth 미완료 → `/auth/chzzk?uid=...` 재로그인

### 후원이 안 옴

- bridge 실행 여부, Scope **후원 조회**, OAuth 계정이 스트리머 본인인지 확인
- `/status`의 `last_error`

### Redis 연결 실패

- `redis-cli ping` → `PONG`
- bridge 터미널 로그 확인

---

## 다음 단계

1. **Phase 4** — bridge → SteamAPI `POST /events`
2. **Phase 6** — OAuth 토큰 암호화

루트 [README.md](../README.md) 참고.
