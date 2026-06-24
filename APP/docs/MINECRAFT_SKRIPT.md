# 마인크래프트 후원 효과 (NR-Donation + Skript)

steamAPI는 치지직 후원을 **NR-Donation 플러그인 WebSocket(8888)** 으로 넘깁니다.  
NR-Donation은 **`DonationEvent`** 만 발생시키고, TNT·몹 소환 등 **인게임 효과는 Skript**에서 처리합니다.

```
치지직 → Bridge → Portal → NR-Donation WS → DonationEvent → Skript
```

---

## 필요한 것 (마크 서버)

| 구성 | 설명 |
|------|------|
| **Paper / Spigot** | 1.17+ 권장 (Docker `itzg/minecraft-server` + `TYPE: PAPER`) |
| **NR-Donation 플러그인** | `plugin` 모듈 shadowJar → `plugins/` |
| **Skript** | 스크립트 엔진 |
| **Skript-Reflect** | NR-Donation **커스텀 이벤트** 수신용 애드온 |

> NR-Donation **클라이언트 모드는 사용하지 않습니다.** (steamAPI가 치지직 WS를 대신 수신)

---

## NR-Donation 플러그인 설정

`plugins/NR-Donation/config.yml` (또는 플러그인이 생성한 config):

```yaml
Server:
  type: "main"
  host: "0.0.0.0"
  port: 8888
```

Docker compose에 **8888 포트** 노출:

```yaml
ports:
  - "25565:25565"
  - "8888:8888"
```

서버 로그에 `WebSocket server started` / `WS started` 가 보이면 OK.

steamAPI Portal `.env`:

```env
NR_DONATION_WS_URL=ws://127.0.0.1:8888
```

---

## Skript 설치

1. 서버 **plugins** 폴더 확인:
   ```bash
   ls ~/minecraft-server/data/plugins/
   ```
2. **Skript** jar가 없으면 [Skript 릴리스](https://github.com/SkriptLang/Skript/releases)에서 Paper용 jar 받기  
   → `~/minecraft-server/data/plugins/Skript.jar` (이름은 아무거나 가능)
3. **Skript-Reflect** jar도 같은 폴더에  
   → [skript-reflect 릴리스](https://github.com/SkriptLang/skript-reflect/releases)
4. MC 서버 **재시작** (또는 `docker compose restart mc`)
5. 스크립트 폴더가 없으면 직접 만들기:
   ```bash
   mkdir -p ~/minecraft-server/data/plugins/Skript/scripts
   cp ~/steamAPI/APP/skript/donation-effects.sk \
      ~/minecraft-server/data/plugins/Skript/scripts/
   ```
6. 스크립트 반영 및 reload (Mac Mini, Docker):

   ```bash
   cd ~/steamAPI && git pull
   cp ~/steamAPI/APP/skript/donation-effects.sk \
      ~/minecraft-server/data/plugins/Skript/scripts/
   docker exec -i minecraft rcon-cli sk reload donation-effects
   ```

   > `sk` 는 **Mac 터미널 명령이 아닙니다.** 마크 서버 콘솔(또는 위 `rcon-cli`)에서만 실행합니다.  
   > `docker attach` 대신 `rcon-cli` 사용을 권장합니다.

   게임 안(OP)에서도 가능: `/sk reload donation-effects`

> `cp: .../Skript/scripts does not exist` → **Skript 미설치**이거나 **한 번도 서버를 안 켠** 상태입니다. 위 2~5단계 순서대로 진행하세요.

예제 파일: [`../skript/donation-effects.sk`](../skript/donation-effects.sk)

---

## DonationEvent 필드

| Java 메서드 | 의미 | steamAPI 경로 예시 |
|-------------|------|-------------------|
| `getPlatform()` | 플랫폼 | `chzzk` |
| `getSender()` | 후원자 닉 | `TEST` |
| `getAmount()` | 금액 (원) | `1000` |
| `getMessage()` | 후원 메시지 | (치지직 메시지) |
| `getPlayer()` | **스트리머** 플레이어 | Portal `mc_username` 과 동일 닉, **접속 중** |

이벤트는 **해당 스트리머가 서버에 접속 중일 때만** 발생합니다.

---

## Skript 예제 (Skript-Reflect 2.6+)

```skript
import:
  net.teujaem.nrDonation.event.DonationEvent

on DonationEvent:
    set {_platform} to event.getPlatform()
    set {_sender} to event.getSender()
    set {_amount} to event.getAmount()
    set {_message} to event.getMessage()
    set {_player} to event.getPlayer()

    if {_player} is not set:
        stop

    broadcast "&6[후원/&e%{_platform}%&6] &f%{_sender}% &7→ &e%{_player}% &6%{_amount}%원"
    if {_message} is set:
        if {_message} is not "":
            broadcast "&7메시지: %{_message}%"

    if {_amount} >= 10000:
        loop 3 times:
            spawn primed tnt at location 2 meters above {_player}
    else if {_amount} >= 1000:
        spawn primed tnt at location 2 meters above {_player}
```

> `on event "패키지.클래스"` 는 **구 skript-mirror** 문법입니다.  
> Skript-Reflect 2.6 은 위처럼 **`import` + `on DonationEvent`** 를 씁니다.

금액 구간·TNT 개수는 [`skript/donation-effects.sk`](../skript/donation-effects.sk) 에서 수정하세요.

---

## 동작 확인

1. steamAPI **bridge** + **portal** 실행, 스트리머 OAuth 완료 (`listening`)
2. 스트리머가 **등록한 마크 닉**으로 서버 접속
3. 치지직 테스트 후원 또는 치지직 개발자 도구 후원
4. 마크 로그: `user//event//donation//chzzk//...`
5. Skript: 채팅 알림 + 설정한 효과

admin `/admin` 의 **마크 서버 로그** 패널으로 WS 수신 여부를 볼 수 있습니다.

---

## 자주 나는 문제

| 증상 | 확인 |
|------|------|
| WS 로그는 있는데 Skript 무반응 | `latest.log` 에 `Can't understand ... on event` → **import 문법**으로 수정 후 `sk reload donation-effects` |
| WS 로그 자체가 없음 | Portal `NR_DONATION_WS_URL`, Docker 8888 |
| 이벤트가 안 옴 | 스트리머 **오프라인** 또는 `mc_username` 불일치 |
| `event-value` 오류 | Skript / Skript-Reflect 버전, 클래스명 오타 |

---

## 참고

- NR-Donation README: 플러그인·모드 빌드 방법 (Skript 예시는 없음)
- NR-Donation 디스코드: 추가 API·이벤트 문서
