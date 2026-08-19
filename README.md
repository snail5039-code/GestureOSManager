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

# 3) 파이썬 에이전트
cd py
pip install -r requirements.txt   # 최초 1회
python main.py
```

`/api/health` 로 매니저 서버 상태를 볼 수 있습니다.

```bash
curl http://127.0.0.1:8080/api/health
# {"ok":true,"agentConnected":true,"hudClients":1,"profileDbAvailable":false}
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

설치본을 쓰려면 매니저 서버와 파이썬 에이전트가 이미 떠 있어야 합니다.
(두 프로세스를 앱이 직접 띄우도록 만드는 작업은 아직 남아 있습니다.)

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

## 알려진 제한

- 폰 연동(화면 스트리밍 / 원격 입력)에 인증이 없습니다.
- 매니저 서버 API(8080)에도 인증이 없어, 방문한 웹페이지가 로컬 API를 호출할 수 있습니다.
- 학습 모델이 `%TEMP%` 에 저장되어 임시 파일 정리 도구에 지워질 수 있습니다.
