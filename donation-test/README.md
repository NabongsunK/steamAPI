# 치지직 후원 API 테스트 서버

치지직 Open API **Session WebSocket**으로 후원(`DONATION`) 이벤트를 받아 보는 Python 테스트 앱입니다.  
본 프로젝트 본편(Bridge · SteamAPI) 구현 전에 OAuth와 후원 수신이 되는지 확인할 때 사용합니다.

**관련 문서**

- [Session API](https://chzzk.gitbook.io/chzzk/chzzk-api/session)
- [Authorization (OAuth)](https://chzzk.gitbook.io/chzzk/chzzk-api/authorization)
- [참고사항 (Client / Bearer 인증)](https://chzzk.gitbook.io/chzzk/chzzk-api/tips)

---

## 사전 준비 (치지직 개발자 센터)

1. [치지직 Open API](https://chzzk.gitbook.io/chzzk)에서 애플리케이션 등록
2. **Client ID**, **Client Secret** 발급
3. **로그인 리디렉션 URL** 등록
   - 기본값: `http://localhost:3000/auth/chzzk/callback`
   - `.env`의 `CHZZK_REDIRECT_URI`와 **완전히 동일**해야 합니다.
4. Scope에서 **후원 조회** 체크

> 후원 WebSocket은 **스트리머 본인 계정** OAuth가 필요합니다. Client ID/Secret만으로는 후원 이벤트를 받을 수 없습니다.

---

## 설치

Python 3.10 이상 권장. **Redis** 가 로컬에서 실행 중이어야 합니다.

**macOS / Linux**

```bash
cd donation-test
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt

# Redis (mac)
brew install redis
brew services start redis
# 또는 한 번만: redis-server

# Redis (Ubuntu/Debian)
# sudo apt install redis-server && sudo systemctl start redis
```

---

## 환경 변수

`.env.example`을 복사해 `.env`를 만듭니다.

```bash
# macOS / Linux
cp .env.example .env
```

| 변수                  | 설명                  | 예시                                        |
| --------------------- | --------------------- | ------------------------------------------- |
| `CHZZK_CLIENT_ID`     | 앱 Client ID          | `fefb6bbb-...`                              |
| `CHZZK_CLIENT_SECRET` | 앱 Client Secret      | `VeIMuc9X...`                               |
| `CHZZK_REDIRECT_URI`  | OAuth 콜백 URL        | `http://localhost:3000/auth/chzzk/callback` |
| `PORT`                | HTTP 서버 포트        | `3000`                                      |
| `TOKEN_FILE`          | (선택) 토큰 저장 경로 | `data/tokens.json`                          |
| `REDIS_URL`           | Redis 연결 URL        | `redis://127.0.0.1:6379/0`                  |
| `SQLITE_PATH`         | 후원 DB 파일 경로     | `data/donations.db`                         |
| `DONATION_LIST_LIMIT` | `/donations` 기본 개수 | `50`                                       |

`.env`는 git에 올라가지 않습니다 (루트 `.gitignore` 처리).

---

## 실행

```powershell
cd donation-test
python server.py
```

기본 주소: http://localhost:3000

---

## 사용 방법

### 1. OAuth (최초 1회)

1. 브라우저에서 http://localhost:3000 접속
2. **치지직 로그인 (OAuth)** 클릭
3. **본인 스트리머 계정**으로 로그인·권한 동의
4. 콜백 후 메인 페이지로 돌아오면 토큰이 `data/tokens.json`에 저장됩니다.

직접 OAuth URL로 가려면:

```
http://localhost:3000/auth/chzzk
```

### 2. 후원 수신 확인

OAuth 완료 후 백그라운드 리스너가 자동으로:

1. `GET /open/v1/sessions/auth` → WebSocket URL 획득
2. Socket.IO 연결 → `sessionKey` 수신
3. `POST .../subscribe/donation` → 후원 구독
4. `DONATION` 이벤트 수신

**본인 채널**에 후원(치즈 등)을 보내 테스트합니다.

- **터미널**: `후원 수신` → `Redis 큐 적재` → `SQLite 저장` 로그
- **영구 목록**: http://localhost:3000/donations (SQLite)
- **Redis 최근 캐시**: http://localhost:3000/donations/recent

### 3. 상태 확인

http://localhost:3000/status

| 필드               | 의미                                                          |
| ------------------ | ------------------------------------------------------------- |
| `listener_status`  | `waiting_for_oauth` · `connecting` · `listening` · `error` 등 |
| `session_key`      | 연결된 세션 키 (일부만 표시)                                  |
| `last_error`       | 마지막 오류 메시지                                            |
| `has_access_token` | OAuth 완료 여부                                               |
| `storage.redis_connected` | Redis 연결 여부                                        |
| `storage.queue_pending`   | 아직 SQLite에 안 들어간 큐 대기 건수                  |
| `storage.sqlite_total`    | SQLite 누적 후원 건수                                 |
| `storage.worker_running`  | Redis→SQLite 워커 실행 여부                           |

리스너 재시작:

```powershell
curl -X POST http://localhost:3000/listener/restart
```

---

## HTTP API

| 메서드 | 경로                   | 설명                             |
| ------ | ---------------------- | -------------------------------- |
| `GET`  | `/`                    | 안내 페이지                      |
| `GET`  | `/auth/chzzk`          | 치지직 OAuth 시작                |
| `GET`  | `/auth/chzzk/callback` | OAuth 콜백 (치지직이 호출)       |
| `GET`  | `/status`              | 리스너·토큰·저장소 상태 (JSON)   |
| `GET`  | `/donations`           | SQLite 후원 목록 (`?limit=&offset=`) |
| `GET`  | `/donations/recent`    | Redis 최근 캐시 (빠른 조회)      |
| `POST` | `/listener/restart`    | 리스너 + 큐 워커 재시작          |

### `/donations` 응답 예시 (SQLite)

```json
{
  "source": "sqlite",
  "count": 1,
  "total": 12,
  "queue_pending": 0,
  "donations": [
    {
      "id": 12,
      "received_at": "2026-06-11T12:00:00+00:00",
      "donator_nickname": "홍길동",
      "pay_amount": "1000",
      "donation_text": "테스트",
      "donation_type": "CHAT",
      "channel_id": "...",
      "donator_channel_id": "...",
      "created_at": "2026-06-11 12:00:01"
    }
  ]
}
```

---

## 저장 구조 (Redis → SQLite)

후원 이벤트는 메모리 대신 **Redis 큐 + SQLite** 로 처리합니다.

```mermaid
flowchart LR
    WS[WebSocket DONATION] --> RQ[Redis donations:queue]
    WS --> RC[Redis donations:recent]
    RQ --> WK[큐 워커 BLPOP]
    WK --> SQL[(SQLite donations.db)]
    API["GET /donations"] --> SQL
    API2["GET /donations/recent"] --> RC
```

| 저장소 | Redis 키 / 파일 | 역할 |
|--------|-----------------|------|
| **큐** | `donations:queue` | 후원 JSON 대기열 (RPUSH / BLPOP) |
| **최근 캐시** | `donations:recent` | 최근 50건 빠른 조회 (LPUSH + LTRIM) |
| **영구 저장** | `data/donations.db` | 워커가 큐에서 꺼내 INSERT |

1. WebSocket `DONATION` 수신 → Redis 큐 + recent 적재  
2. 백그라운드 워커가 `BLPOP`으로 꺼냄 → SQLite `donations` 테이블 INSERT  
3. API는 SQLite에서 페이지네이션 조회 (`limit` / `offset`)

---

## 동작 흐름

```mermaid
sequenceDiagram
    participant U as 브라우저
    participant S as server.py
    participant C as 치지직 API
    participant W as WebSocket

    U->>S: GET /auth/chzzk
    S->>C: account-interlock (OAuth)
    C-->>U: 로그인·동의
    C-->>S: callback ?code=&state=
    S->>C: POST /auth/v1/token
    S->>S: tokens.json 저장
    S->>C: GET /open/v1/sessions/auth
    S->>W: Socket.IO 연결
    W-->>S: SYSTEM connected (sessionKey)
    S->>C: POST subscribe/donation
    W-->>S: DONATION 이벤트
    S->>S: Redis 큐 적재
    S->>S: 워커 → SQLite 저장
```

---

## 파일 구조

```
donation-test/
├── README.md            # 이 문서
├── server.py            # FastAPI · OAuth · HTTP API
├── chzzk_api.py         # 토큰 발급/갱신, 세션 URL, 후원 구독
├── donation_listener.py # Socket.IO 후원 리스너
├── donation_store.py    # Redis 큐 · SQLite · 워커
├── requirements.txt
├── .env.example
├── .env                 # 직접 생성 (git 제외)
└── data/
    ├── tokens.json      # OAuth 토큰 (git 제외)
    └── donations.db     # 후원 영구 저장 (git 제외)
```

---

## 자주 나는 문제

### `INVALID_CLIENT` / 401

- `.env`의 Client ID·Secret이 콘솔 값과 일치하는지 확인
- Redirect URI가 치지직 앱 설정과 **한 글자도 다르지 않은지** 확인 (`http` vs `https`, 끝 `/` 등)

### `listener_status: waiting_for_oauth`

- `/auth/chzzk`로 OAuth를 아직 안 했거나 `data/tokens.json`이 없음

### `FORBIDDEN` / 후원이 안 옴

- 앱 Scope에 **후원 조회**가 켜져 있는지 확인
- OAuth한 계정이 **해당 채널의 스트리머 본인**인지 확인
- 후원을 **구독한 채널(본인 방송 채널)**에 보냈는지 확인

### `INVALID_TOKEN`

- Access Token 만료 (1일). 서버가 Refresh Token으로 자동 갱신 시도
- Refresh도 만료됐으면(30일) `/auth/chzzk`로 다시 로그인

### Socket 연결 실패

- 방화벽·VPN 이슈 확인
- `/status`의 `last_error` 확인 후 `POST /listener/restart`

### Redis 연결 실패

- `redis-cli ping` → `PONG` 이어야 함
- mac: `brew services start redis` 또는 `redis-server`
- `.env`의 `REDIS_URL` 확인 (`redis://127.0.0.1:6379/0`)

### 후원은 왔는데 `/donations`에 없음

- `/status` → `storage.queue_pending` 이 0보다 크면 워커 지연/오류
- `storage.worker_last_error` 확인
- `/donations/recent` 에는 있는데 `/donations`에 없으면 SQLite INSERT 실패 가능

---

## 토큰·보안

- `data/tokens.json`에 Access/Refresh Token이 평문 저장됩니다. **테스트용**으로만 사용하세요.
- 본편 Bridge 구현 시에는 DB 암호화 저장을 권장합니다 (루트 `README.md` 참고).

---

## 다음 단계

후원 수신이 확인되면 본 프로젝트에서:

1. **Bridge** — uid별 Session WS + `POST /events` 전송
2. **SteamAPI** — `events_config` 조회 후 MC RCON 실행

루트 [README.md](../README.md)의 개발 로드맵을 참고하세요.
