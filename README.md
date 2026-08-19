# GestureOS Manager

손 제스처로 Windows 마우스·키보드·PPT·그리기를 제어하는 접근성(대체 입력) 도구와,
그 에이전트를 켜고 끄고 학습시키는 데스크톱 관리 앱입니다.

## 구성

이 리포는 프로세스 네 개로 이루어져 있습니다. **실행 순서가 중요합니다.**

| 폴더 | 무엇 | 포트 |
| --- | --- | --- |
| `py/` | 파이썬 에이전트 — 카메라로 손을 인식해 실제 입력을 만든다 | (WS 클라이언트) |
| `gestureOSManager/` | 매니저 서버 (Spring Boot) — 에이전트와 UI 사이의 중계·설정·학습 API | **8080** |
| `front/` | 매니저 UI (Electron + React) | **5173** (개발 시) |
| `PhoneController-master/` | 안드로이드 앱 — 폰을 컨트롤러로 쓰는 선택 기능 | — |

계정·게시판 기능은 별 리포([GestureOSManagerWeb](https://github.com/snail5039-code/GestureOSManagerWeb))의
서버(**8082**)를 사용합니다. 로그인·학습 프로필 동기화를 쓰려면 그 서버도 함께 띄워야 합니다.

## 개발 환경에서 실행

```bash
# 1) 매니저 서버 (8080)
cd gestureOSManager
./mvnw spring-boot:run

# 2) 매니저 UI (5173 + Electron 창)
cd front
npm install
npm run manager:electron

# 3) 파이썬 에이전트 (파이썬 3.12 필요 — 아래 주의 참고)
cd py
pip install -r requirements.txt   # 최초 1회
python main.py
```

> **파이썬 버전 주의**
> 에이전트는 mediapipe 의 `mp.solutions.hands` API 를 쓰는데, **파이썬 3.13 용 mediapipe 에는
> 이 API 가 아예 없습니다**(3.13 빌드는 `Image`, `ImageFormat`, `tasks` 만 포함).
> 게다가 requirements.txt 가 고정한 `mediapipe==0.10.21` 은 3.13 에 설치조차 되지 않습니다.
> 그래서 **파이썬 3.12 이하**에서 실행해야 합니다.
>
> ```bash
> pyenv install 3.12.8
> ~/.pyenv/pyenv-win/versions/3.12.8/python.exe -m venv .venv
> .venv/Scripts/python.exe -m pip install -r requirements.txt
> .venv/Scripts/python.exe main.py
> ```
>
> 3.13 에서 쓰려면 hands_agent 를 mediapipe Tasks API 로 옮기는 작업이 필요합니다.

`/api/health` 로 매니저 서버 상태를 볼 수 있습니다.

```bash
curl http://127.0.0.1:8080/api/health
# {"ok":true,"agentConnected":true,"hudClients":1,"uiClients":1,"profileDbAvailable":false}
```

`agentConnected` 가 `false` 면 파이썬 에이전트가 붙지 않은 상태입니다.

### 에이전트 실행 옵션

| 옵션 | 뜻 |
| --- | --- |
| `--phone` | 폰 연동을 켠다. **기본은 꺼짐** (아래 주의 참고) |
| `--no-hud` | 화면 위 HUD 오버레이를 띄우지 않는다 |
| `--no-inject` | 실제 입력을 만들지 않는다 (인식만 확인할 때) |
| `--no-ws` | 매니저 서버에 붙지 않는다 |
| `--start-enabled` | 켜진 상태로 시작 |
| `--agent=color` | 손 대신 색 추적 모드로 시작 |

> **폰 연동 주의**
> `--phone` 을 주면 이 PC가 같은 네트워크에 두 가지를 공개합니다.
> **TCP 8081** — 화면 전체 실시간 스트리밍, **UDP 39500** — 마우스/키보드 원격 입력.
> 현재 두 경로 모두 인증이 없습니다. 신뢰할 수 없는 Wi-Fi(카페·학원·회사 게스트망)에서는
> 켜지 마세요. 페어링에 시크릿을 붙이는 작업이 남아 있습니다.

## 설치본 만들기

```bash
cd front
npm run app:dist      # release/ 에 NSIS 설치 파일 생성
npm run app:pack      # 설치 파일 없이 폴더만 (release/win-unpacked)
```

설치본은 개발 서버 없이 동작합니다. Electron 메인 프로세스가 `gosapp://` 스킴으로
빌드 결과를 서빙하고, `/api` 요청을 개발용 Vite proxy 와 같은 규칙으로 중계합니다.

| 요청 | 중계 대상 |
| --- | --- |
| `/api/auth/**`, `/api/members/**` | 계정 서버 `http://127.0.0.1:8082` |
| `/api/**`, `/motion/**` | 매니저 서버 `http://127.0.0.1:8080` |

포트를 바꿨다면 환경변수 `GOS_AGENT_ORIGIN` / `GOS_ACCOUNT_ORIGIN` 으로 넘길 수 있습니다.

## 설치본으로 사용하기

**설치 파일만으로는 아직 동작하지 않습니다.** 앱은 UI 이고, 실제 인식과 입력은 매니저
서버(Java)와 파이썬 에이전트가 합니다. 앱이 이 두 프로세스를 직접 띄우게 만드는 작업이
아직 남아 있어서, 지금은 손으로 함께 실행해야 합니다.

### 미리 필요한 것

| 필요 | 버전 | 왜 |
| --- | --- | --- |
| Java | 17 이상 | 매니저 서버(8080) |
| Python | **3.12** (3.13 불가) | 에이전트 — 위 "파이썬 버전 주의" 참고 |
| 웹캠 | — | 손 인식 |

로그인·학습 프로필 동기화까지 쓰려면 계정 서버(8082)도 함께 띄워야 합니다.
로그인 없이도 기본 프로필로 제스처 제어는 됩니다.

### 실행 순서

```bash
# 1) 매니저 서버 (먼저 떠 있어야 앱이 붙는다)
cd gestureOSManager && ./mvnw spring-boot:run

# 2) 파이썬 에이전트 (3.12 가상환경에서)
cd py && .venv/Scripts/python.exe main.py

# 3) 설치한 "GestureOS Manager" 실행
```

### 잘 붙었는지 확인하기

앱 상단 상태 카드가 이렇게 보이면 정상입니다.

| 항목 | 정상 값 |
| --- | --- |
| 연결 | 연결됨 (끊김이면 에이전트가 안 떠 있음) |
| FPS | 25~35 (0.0 이면 카메라를 못 열었음) |
| 실행 | 시작 버튼을 누르면 "실행 중" |

서버 쪽에서도 확인할 수 있습니다.

```bash
curl http://127.0.0.1:8080/api/health
# {"ok":true,"agentConnected":true,"hudClients":0,"uiClients":1,"profileDbAvailable":false}
```

`agentConnected` 는 에이전트, `uiClients` 는 앱 창입니다. 둘 다 1 이상이어야 합니다.

### 처음 쓸 때

1. **시작** 을 누릅니다. 카메라가 없으면 안내 창이 뜹니다.
2. 모드를 고릅니다. 기본은 **마우스** 입니다.
3. 카메라 앞에 손을 펴면(OPEN_PALM) 커서가 움직입니다. 기본 매핑은 이렇습니다.

| 제스처 | 마우스 모드 동작 |
| --- | --- |
| 손 펴기 (OPEN_PALM) | 커서 이동 |
| 검지 집기 (PINCH_INDEX) | 클릭 / 드래그 |
| 브이 (V_SIGN) | 우클릭 |
| 주먹 (FIST) | 잠금 토글 · 다른 손으로 스크롤 |

매핑은 **설정** 화면에서 바꿀 수 있습니다.
잘 안 잡히면 **학습** 화면에서 본인 손으로 제스처를 학습시킬 수 있습니다.

### 안 될 때

| 증상 | 확인할 것 |
| --- | --- |
| 연결: 끊김 | 에이전트가 떠 있는지, 로그에 `WS connected` 가 있는지 |
| FPS 0.0 | 다른 앱이 카메라를 잡고 있는지 |
| 상태 조회 실패 (401) | 서버를 재시작했으면 앱도 다시 켜세요(세션 토큰이 갱신됩니다) |
| 커서가 안 움직임 | 시작을 눌렀는지, 잠금이 꺼져 있는지, `--no-inject` 로 띄우지 않았는지 |
| 로그인이 안 됨 | 계정 서버(8082)가 떠 있는지 |

## 로그인과 학습 프로필

학습 프로필은 계정별로 분리됩니다. 매니저 UI 는 매니저 서버에 액세스 토큰을 함께 보내고,
매니저 서버는 그 토큰을 계정 서버(`GOS_ACCOUNT_ORIGIN`, 기본 8082)의 `/api/members/me` 에
확인해서 회원 ID 를 정합니다. 확인되지 않으면 게스트로 처리되어 기본 프로필만 쓸 수 있습니다.

예전에는 클라이언트가 보낸 `X-User-Id` 헤더의 숫자를 그대로 회원 ID 로 썼습니다.
헤더만 바꾸면 남의 학습 프로필을 읽고 지울 수 있었습니다.

## 학습 프로필 DB (선택)

학습시킨 제스처 모델을 계정별로 DB에 동기화하는 기능이며 **기본은 꺼져 있습니다.**
로컬 파일 저장만으로도 학습·사용이 됩니다.

켜려면 PostgreSQL 과 테이블이 필요합니다.

```bash
psql -U sltuser -d slt -f gestureOSManager/src/main/resources/db/schema-profile.sql
GOS_PROFILE_DB_ENABLED=true ./mvnw spring-boot:run
```

DB에 닿지 못하면 예외 대신 로컬 파일 저장으로 내려가고, `/api/health` 의
`profileDbAvailable` 이 `false` 로 보입니다.

## 설정값

`gestureOSManager/.env.example` 참고. 전부 기본값이 있어 그냥 띄워도 동작합니다.

## 로컬 세션 토큰

매니저 서버는 기동할 때마다 임의 토큰을 만들어 `~/.gestureos/session.token` 에 쓰고,
모든 `/api` 요청(헤더 `X-GOS-Token`)과 WebSocket 접속(쿼리 `?token=`)에서 그 토큰을 요구합니다.
`/api/health` 만 예외입니다.

파일을 읽을 수 있는 건 같은 사용자로 실행되는 프로그램(매니저 UI, 파이썬 에이전트)뿐입니다.
그래서 사용자가 열어둔 웹페이지가 `http://localhost:8080/api/control/*` 로 요청을 보내
제스처 에이전트를 조작하는 경로가 막힙니다. 서버는 `127.0.0.1` 에만 바인딩되어
같은 네트워크의 다른 기기도 접근할 수 없습니다.

토큰은 개발 중에는 Vite dev proxy 가, 설치본에서는 Electron 메인 프로세스가 붙입니다.
렌더러 자바스크립트에는 들어가지 않습니다(WebSocket 접속용으로만 IPC 로 받아갑니다).

브라우저에서 `http://localhost:5173` 을 직접 열어 디버깅해야 한다면
`GOS_AUTH_ENABLED=false` 로 끌 수 있습니다. 끄면 위 보호도 사라집니다.

## 알려진 제한

- 폰 연동(화면 스트리밍 / 원격 입력)에 인증이 없습니다. 그래서 기본이 꺼짐입니다.
- 학습 모델이 `%TEMP%` 에 저장되어 임시 파일 정리 도구에 지워질 수 있습니다.
- 다중 모니터에서 마우스 모드 포인터 좌표가 1을 넘을 수 있습니다(주 모니터 크기로 정규화).
