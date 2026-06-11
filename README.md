# Chzzk → Minecraft Bridge (Multi-Streamer)

치지직 **후원**·**팔로우** 이벤트를 **여러 스트리머 채널**에서 수집해, **공유 마인크래프트 서버 1대**에 인게임 이벤트를 발생시키는 연동 프로젝트입니다.

**데이터 흐름:** `유저 → 후원/팔로우 → Bridge (채널별 WS + 폴링) → SteamAPI → MC 1대 (uid별 이벤트 규칙)`

| 레이어              | 역할                                                               |
| ------------------- | ------------------------------------------------------------------ |
| **Bridge (1대)**    | 스트리머(채널)별 Session WS + Follow Poller, DB 토큰 기반 N개 운영 |
| **SteamAPI (1대)**  | `streamerUid`로 **이벤트 규칙** 조회 → **동일 MC** RCON 실행       |
| **DB**              | 채널별 OAuth, `known_followers`, uid별 `events_config`             |
| **Minecraft (1대)** | `:25565` + RCON `:25575`, ngrok 1개로 외부 접속                    |

> **멀티 스트리머** = 치지직 채널 N개 (OAuth·후원·팔로우 수집 분리). **마크 서버는 1대 공유**합니다.

---

## 개요

```mermaid
flowchart TB
    subgraph Streamers["스트리머 N명"]
        S1["스트리머 A"]
        S2["스트리머 B"]
    end

    CHZZK["치지직 API\nSession WS · Channel REST"]

    subgraph Bridge["Bridge (1개)"]
        WS1["WS Client A"]
        WS2["WS Client B"]
        POLL1["Follow Poller A"]
        POLL2["Follow Poller B"]
    end

    DB[("DB\nstreamers\nknown_followers")]

    STEAM["SteamAPI"]
    MC["Minecraft Server\n(공유 1대)"]
    NGROK["ngrok"]

    S1 & S2 -->|"각자 OAuth"| CHZZK
    Bridge <-->|"토큰 · 상태"| DB
    CHZZK --> WS1 & WS2
    CHZZK --> POLL1 & POLL2
    Bridge -->|"POST /events\n{ streamerUid }"| STEAM
    STEAM -->|"events_config\nby uid"| DB
    STEAM -->|"RCON :25575"| MC
    MC --- NGROK
```

| 이벤트      | Bridge 수신        | 치지직 API                                                                     | SteamAPI → MC                            |
| ----------- | ------------------ | ------------------------------------------------------------------------------ | ---------------------------------------- |
| **후원**    | WebSocket (실시간) | [Session API](https://chzzk.gitbook.io/chzzk/chzzk-api/session) — `DONATION`   | uid별 `events_config` → **공유 MC** RCON |
| **팔로우**  | REST 폴링          | [Channel API](https://chzzk.gitbook.io/chzzk/chzzk-api/channel) — `/followers` | uid별 `events_config`                    |
| 구독 (선택) | WebSocket (실시간) | Session API — `SUBSCRIPTION`                                                   | uid별 `events_config`                    |

> Session API는 `CHAT` · `DONATION` · `SUBSCRIPTION`만 WebSocket 제공. **팔로우는 REST 폴링 + DB diff**만 가능.

---

## 사전 준비

### 1. 치지직 개발자 등록

1. [치지직 Open API](https://chzzk.gitbook.io/chzzk) 애플리케이션 등록
2. `Client ID`, `Client Secret` 발급
3. OAuth Redirect URI 등록 (예: `http://localhost:3000/auth/chzzk/callback`)
4. 스트리머마다 OAuth → token은 **DB `streamers` 테이블**에 저장

| Scope            | 용도                |
| ---------------- | ------------------- |
| 후원 조회        | 후원 WebSocket 구독 |
| 채널 팔로워 조회 | 팔로우 REST 폴링    |
| (선택) 구독 조회 | 구독 WebSocket 구독 |

- Access Token 만료: **1일** · Refresh Token: **30일** (일회용 갱신)

### 2. DB

PostgreSQL (또는 SQLite 개발용). Bridge·SteamAPI가 **동일 DB** 공유.

```bash
psql $DATABASE_URL -f src/db/schema.sql
```

### 3. 마인크래프트 서버 (공유 1대)

모든 스트리머가 **동일 MC 서버**에 이벤트를 발생시킵니다. RCON은 SteamAPI `.env` 또는 DB 공통 설정 1곳에서 관리합니다.

```properties
server-port=25565
enable-rcon=true
rcon.port=25575
rcon.password=YOUR_SECURE_PASSWORD
broadcast-rcon-to-ops=false
```

스트리머 A/B 후원이 와도 **같은 월드**에 명령이 실행됩니다. uid별로 **다른 명령·메시지**만 `events_config`에서 구분합니다.

### 4. ngrok (게임 접속용, 1개)

```bash
ngrok tcp 25565
```

- MC 1대 → ngrok 터널 **1개**
- **Bridge → SteamAPI → RCON** 경로는 로컬 전용, ngrok 무관

---

## 네트워크 구성

```mermaid
flowchart TB
    USER["👤 유저"]

    subgraph ChzzkCloud["☁️ 치지직"]
        SESSION["Session API\nWebSocket"]
        CHANNEL["Channel API\nREST"]
    end

    subgraph AppLayer["애플리케이션 (로컬)"]
        BRIDGE["Bridge\n채널 A · B 각각 WS + Poll"]
        STEAM["SteamAPI"]
        DB[("DB\nstreamers\nknown_followers")]
    end

    subgraph GameLayer["🔒 MC 공유 (로컬 1대)"]
        MC["Minecraft :25565"]
        RCON["RCON :25575"]
        NGROK["ngrok\ntcp 25565"]
    end

    PLAYER["🎮 플레이어"]

    USER --> SESSION & CHANNEL
    SESSION -->|"WS 후원·구독"| BRIDGE
    CHANNEL -->|"REST /followers"| BRIDGE
    BRIDGE <-->|"채널별 토큰 · 팔로워"| DB
    BRIDGE -->|"POST /events\n{ streamerUid }"| STEAM
    STEAM -->|"events_config by uid"| DB
    STEAM --> RCON
    RCON --> MC
    MC <-->|"터널 1개"| NGROK
    NGROK <-->|"외부 접속"| PLAYER
```

| 구간                 | 프로토콜                       | 비고                         |
| -------------------- | ------------------------------ | ---------------------------- |
| Session API → Bridge | WebSocket                      | **채널(uid)별** WS Client    |
| Channel API → Bridge | REST 폴링                      | **채널(uid)별** Poller       |
| Bridge → SteamAPI    | `POST /events { streamerUid }` | 어느 채널 이벤트인지 구분    |
| SteamAPI → MC        | RCON **1개** (공유)            | uid → `events_config`만 분기 |
| MC → 플레이어        | ngrok **1개**                  | `:25565` 터널                |

---

## UID · DB 스키마

내부 **`streamer_uid`**(UUID)와 치지직 **`chzzk_channel_id`**를 분리합니다.

| 식별자             | 용도                              |
| ------------------ | --------------------------------- |
| `streamer_uid`     | Bridge ↔ SteamAPI ↔ DB 전 구간 PK |
| `chzzk_channel_id` | Session 구독, `/followers` 폴링   |

```sql
CREATE TABLE streamers (
  uid               UUID PRIMARY KEY,
  chzzk_channel_id  TEXT UNIQUE NOT NULL,
  channel_name      TEXT,
  access_token      TEXT NOT NULL,       -- 암호화 저장 권장
  refresh_token     TEXT NOT NULL,
  token_expires_at  TIMESTAMPTZ NOT NULL,
  events_config     JSONB NOT NULL,      -- uid별 이벤트 → 마크 명령 매핑
  mc_target_player  TEXT,                -- (선택) execute at {닉네임} — 스트리머별 MC 플레이어
  is_active         BOOLEAN DEFAULT true,
  created_at        TIMESTAMPTZ DEFAULT now(),
  updated_at        TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE known_followers (
  streamer_uid        UUID REFERENCES streamers(uid),
  follower_channel_id TEXT NOT NULL,
  follower_name       TEXT,
  followed_at         TIMESTAMPTZ,
  PRIMARY KEY (streamer_uid, follower_channel_id)
);
```

RCON(`MC_HOST`, `MC_RCON_PORT`, `MC_RCON_PASSWORD`)는 **SteamAPI `.env` 1곳** — MC 1대 공유.

**uid별로 달라지는 것:** OAuth · `chzzk_channel_id` · `known_followers` · `events_config` · (선택) `mc_target_player`

---

## Bridge → SteamAPI API 계약

```json
POST /events
Authorization: Bearer {STEAM_API_SECRET}

{
  "streamerUid": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "type": "donation",
  "payload": {
    "donatorNickname": "홍길동",
    "payAmount": "5000",
    "donationText": "크리퍼!"
  }
}
```

SteamAPI 처리:

1. `streamerUid` → DB에서 **`events_config`** 조회
2. Event Router 조건 매칭
3. **공유 MC** RCON으로 명령 실행

`type`: `donation` · `follow` · `subscription`

---

## 스트리머 온보딩

```mermaid
sequenceDiagram
    participant Admin as 관리자 / 스트리머
    participant DB as DB
    participant Bridge as Bridge
    participant C as 치지직
    participant S as SteamAPI

    Admin->>DB: ① 등록 (uid 발급, events_config)
    Admin->>C: ② OAuth (/auth/chzzk?uid=...)
    C-->>Bridge: callback → token + channel_id
    Bridge->>DB: ③ streamers 갱신
    Bridge->>Bridge: ④ uid별 WS Client + Follow Poller 시작
    Bridge->>S: POST /events { streamerUid, type, payload }
    S->>DB: events_config lookup by uid
    S->>S: 공유 MC RCON 명령 실행
```

1. 스트리머 등록 → `streamer_uid` 발급, **`events_config`** 입력
2. OAuth (`/auth/chzzk?uid=...`) → token + `chzzk_channel_id` DB 저장
3. Bridge: uid별 Session WS + Follow Poller 기동
4. 토큰 만료 → uid 기준 Refresh

---

## 모듈 역할

| 모듈                         | 위치        | 책임                                                    |
| ---------------------------- | ----------- | ------------------------------------------------------- |
| **Bridge · Session Manager** | Bridge      | uid별 Session WS Client N개, DONATION·SUBSCRIPTION 수신 |
| **Bridge · Follow Poller**   | Bridge      | uid별 REST 폴링, `known_followers` diff                 |
| **Bridge · Normalizer**      | Bridge      | `{ streamerUid, type, payload }` 포맷으로 SteamAPI POST |
| **Bridge · Auth**            | Bridge      | OAuth callback, uid별 token refresh                     |
| **SteamAPI · Event API**     | 본 프로젝트 | `streamerUid` 검증 · 수신                               |
| **SteamAPI · Event Router**  | 본 프로젝트 | uid별 `events_config` 조건 매칭                         |
| **SteamAPI · RCON Client**   | 본 프로젝트 | **공유 MC 1대** RCON 연결·명령 실행                     |
| **DB**                       | 공유        | streamers, known_followers                              |

### 치지직 API 제한

| 제한               | 값                       |
| ------------------ | ------------------------ |
| WebSocket 연결     | 스트리머(유저)당 **3개** |
| 세션당 이벤트 구독 | **30개**                 |
| 팔로워 REST        | 스트리머 수 × 폴링 주기  |

스트리머 1명당 WS Client 1개 + 구독 2~3개 → Bridge 1대로 **수십 명**까지 가능.

---

## 치지직 연동 상세

### 후원 (Session WebSocket)

[Session API](https://chzzk.gitbook.io/chzzk/chzzk-api/session) — uid별 토큰으로 WS 연결:

```mermaid
sequenceDiagram
    participant B as Bridge (uid A)
    participant C as Chzzk Session API
    participant W as WebSocket
    participant S as SteamAPI
    participant DB as DB
    participant M as MC (공유)

    B->>DB: uid A 토큰 로드
    B->>C: GET /open/v1/sessions/auth
    B->>W: Socket.IO 연결
    B->>C: POST .../subscribe/donation
    W-->>B: DONATION
    B->>S: POST /events { streamerUid: A, ... }
    S->>DB: events_config lookup by uid
    S->>M: RCON execute (공유 MC)
```

```
1. GET  /open/v1/sessions/auth
2. Socket.IO 연결 (1.0.0 ~ 2.0.3) → sessionKey
3. POST /open/v1/sessions/events/subscribe/donation?sessionKey=...
4. DONATION → POST /events { streamerUid }
```

| 필드              | 설명             |
| ----------------- | ---------------- |
| `donatorNickname` | 후원자 닉네임    |
| `payAmount`       | 후원 금액 (원)   |
| `donationText`    | 후원 메시지      |
| `donationType`    | `CHAT` / `VIDEO` |

### 팔로우 (Channel API REST 폴링)

[Channel API](https://chzzk.gitbook.io/chzzk/chzzk-api/channel) — uid별 폴링:

```mermaid
sequenceDiagram
    participant B as Bridge (uid A)
    participant C as Chzzk Channel API
    participant DB as DB
    participant S as SteamAPI

    loop N초마다
        B->>DB: uid A 토큰 로드
        B->>C: GET /open/v1/channels/followers
        C-->>B: 팔로워 목록
        B->>DB: known_followers diff
    end
    B->>S: POST /events { streamerUid: A, type: follow, ... }
```

| 필드          | 설명             |
| ------------- | ---------------- |
| `channelId`   | 팔로워 채널 ID   |
| `channelName` | 팔로워 채널 이름 |
| `createdDate` | 팔로우 일자      |

권장 폴링 주기: **30~60초**

### 구독 (선택, Session WebSocket)

`POST /open/v1/sessions/events/subscribe/subscription?sessionKey=...`

---

## 이벤트 매핑 (`events_config`)

스트리머별로 DB `streamers.events_config` (JSONB)에 저장:

```json
{
  "donation": [
    {
      "id": "small_donation",
      "condition": { "min_amount": 1000, "max_amount": 4999 },
      "actions": [
        "say §6{donator}§f님이 §e{amount}원§f 후원!",
        "execute at @p run summon minecraft:chicken ~ ~ ~"
      ]
    },
    {
      "id": "big_donation",
      "condition": { "min_amount": 5000 },
      "actions": [
        "say §c§l대형 후원! §6{donator} §f→ §e{amount}원",
        "execute at @p run summon minecraft:creeper ~ ~2 ~ {ignited:1b}"
      ]
    }
  ],
  "follow": {
    "actions": [
      "say §a{follower}§f님이 팔로우!",
      "execute at @p run summon minecraft:firework_rocket ~ ~1 ~"
    ]
  }
}
```

| 토큰           | 출처          |
| -------------- | ------------- |
| `{donator}`    | 후원자 닉네임 |
| `{amount}`     | 후원 금액     |
| `{message}`    | 후원 메시지   |
| `{follower}`   | 팔로워 채널명 |
| `{subscriber}` | 구독자 닉네임 |
| `{month}`      | 구독 개월     |
| `{tier_name}`  | 구독 브랜드명 |

---

## 기술 스택

| 영역      | 선택지                                 |
| --------- | -------------------------------------- |
| Bridge    | Node.js / TypeScript (별도 서비스)     |
| SteamAPI  | Node.js / TypeScript — **본 프로젝트** |
| DB        | PostgreSQL (prod) · SQLite (dev)       |
| 치지직    | REST + `socket.io-client` 1.x ~ 2.0.3  |
| MC 연동   | `rcon-client`                          |
| 외부 접속 | ngrok `tcp 25565` (MC 1대)             |

---

## 프로젝트 구조

```
steamAPI/                      ← 본 프로젝트
├── README.md
├── .env.example
├── src/
│   ├── index.ts
│   ├── api/
│   │   ├── events.ts          # POST /events { streamerUid }
│   │   └── streamers.ts       # CRUD · OAuth callback (선택)
│   ├── db/
│   │   ├── schema.sql
│   │   └── streamer.repo.ts
│   ├── router/
│   │   └── event-router.ts    # uid별 events_config 매칭
│   ├── minecraft/
│   │   └── rcon.ts            # 공유 MC RCON 1연결
│   └── types/
│       └── events.ts
└── package.json

bridge/                        ← 별도 서비스
├── src/
│   ├── index.ts               # 기동 시 DB active streamers 로드
│   ├── session/
│   │   └── manager.ts         # uid별 WS Client N개
│   ├── poller/
│   │   └── followers.ts       # uid별 Follow Poller
│   ├── auth/
│   │   └── chzzk-oauth.ts     # /auth/chzzk?uid= callback
│   ├── db/
│   │   └── streamer.repo.ts
│   └── client/
│       └── steam-api.ts
└── package.json
```

---

## 환경 변수

### SteamAPI

```env
STEAM_API_PORT=4000
STEAM_API_SECRET=shared-secret-with-bridge
DATABASE_URL=postgresql://user:pass@localhost:5432/steamapi

# 공유 MC RCON (1대)
MC_HOST=127.0.0.1
MC_RCON_PORT=25575
MC_RCON_PASSWORD=

EVENT_COOLDOWN_SEC=3
LOG_LEVEL=info
```

### Bridge

```env
CHZZK_CLIENT_ID=
CHZZK_CLIENT_SECRET=
CHZZK_REDIRECT_URI=http://localhost:3000/auth/chzzk/callback
DATABASE_URL=postgresql://user:pass@localhost:5432/steamapi
STEAM_API_URL=http://127.0.0.1:4000
STEAM_API_SECRET=shared-secret-with-bridge
FOLLOW_POLL_INTERVAL_SEC=45
```

> OAuth · 채널 ID · `events_config`는 DB `streamers`. RCON · ngrok은 **MC 1대 공유**.

---

## 실행 흐름

```mermaid
flowchart TD
    START([시스템 시작]) --> STEAM[SteamAPI 기동 + DB 연결]
    STEAM --> BRIDGE[Bridge 기동 + DB 연결]
    BRIDGE --> LOAD[DB에서 is_active streamers 로드]

    LOAD --> LOOP["각 streamer_uid"]

    LOOP --> TOKEN{토큰 유효?}
    TOKEN -->|만료| REFRESH[Refresh by uid]
    REFRESH --> WS
    TOKEN -->|유효| WS[Session WS 연결 + donation 구독]
    WS --> POLL[Follow Poller 시작]

    POLL --> EVENT{이벤트}

    EVENT -->|DONATION / SUBSCRIPTION| NORM[Normalizer]
    EVENT -->|FOLLOW diff| NORM

    NORM --> POST["POST /events { streamerUid }"]
    POST --> LOOKUP[SteamAPI: events_config by uid]
    LOOKUP --> EXEC[공유 MC RCON 실행]
    EXEC --> EVENT
```

---

## 개발 로드맵

- [ ] **Phase 1 — DB · SteamAPI**
  - `schema.sql` · streamer repo
  - `POST /events { streamerUid }`
  - 공유 MC RCON · uid별 `events_config` 매칭

- [ ] **Phase 2 — Bridge**
  - DB active streamers 로드
  - uid별 Session WS (DONATION)
  - uid별 Follow Poller + `known_followers`
  - OAuth 온보딩 (`/auth/chzzk?uid=...`)

- [ ] **Phase 3 — 이벤트 · 운영**
  - `events_config` CRUD
  - 쿨다운 · 중복 방지
  - Bridge ↔ SteamAPI 헬스체크
  - ngrok + 공유 MC 연동 확인

---

## 주의사항

1. **스트리머별 OAuth 필수** — 후원·팔로워 조회는 각 스트리머 Access Token 필요
2. **streamer_uid** — Bridge POST부터 **events_config** 선택까지 동일 uid 사용 (RCON은 공유 1개)
3. **세션 제한** — 유저당 WS 3연결, 세션당 구독 30개
4. **익명 후원** — `donatorChannelId`가 `"anonymous"`일 수 있음
5. **ngrok 분리** — 게임 접속만 ngrok. RCON·Bridge·SteamAPI는 내부망
6. **RCON 보안** — RCON(25575) ngrok 노출 금지
7. **토큰 암호화** — DB `access_token` · `refresh_token` 암호화 저장 권장

---

## 참고 링크

- [치지직 Open API](https://chzzk.gitbook.io/chzzk)
- [Session API (WebSocket)](https://chzzk.gitbook.io/chzzk/chzzk-api/session)
- [Channel API (팔로워 조회)](https://chzzk.gitbook.io/chzzk/chzzk-api/channel)
- [Authorization (OAuth)](https://chzzk.gitbook.io/chzzk/chzzk-api/authorization)
- [Session API 테스트 노트 (Gist)](https://gist.github.com/fi-xz/69ce1f35ca1b2318a2b410c0d5757e0f)
