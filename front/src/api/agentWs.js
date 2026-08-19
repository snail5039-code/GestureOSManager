// src/api/agentWs.js
//
// 매니저 UI 가 에이전트 이벤트(APP_START / APP_STOP 같은 제스처 트리거)를 받는 통로.
//
// 엔드포인트는 /ws/ui 다. 예전에는 /ws/agent 에 붙었는데, 그쪽은 서버가 "에이전트 세션"을
// 하나만 등록하는 자리라서 UI 가 접속하는 순간 파이썬 에이전트를 덮어썼다. 그러면 이후
// 모든 명령이 UI 로 가고 에이전트에는 도달하지 않는다(실측 확인). 게다가 UI 가 기다리던
// APP_START/APP_STOP 은 그 소켓으로 오지도 않았다.
//
// 재연결: onclose 에서 로그만 찍고 끝이라, Spring 을 재시작하거나 잠깐 끊기면
// 앱을 다시 켤 때까지 이벤트가 오지 않았다. 파이썬 에이전트 쪽에는 1초 간격
// 재접속 루프가 있어서 양쪽이 비대칭이었다.

const DEFAULT_URL = "ws://127.0.0.1:8080/ws/ui";

/** 재연결 간격(ms). 마지막 값에서 더 늘리지 않는다. */
const RETRY_DELAYS = [1000, 2000, 5000, 10000, 30000];

let ws;
let url = DEFAULT_URL;
let retryIndex = 0;
let retryTimer = null;
/** closeAgentWs() 로 명시적으로 끊은 경우에는 다시 붙지 않는다. */
let manuallyClosed = false;

const listeners = new Set();
const stateListeners = new Set();

function notifyState(state) {
  stateListeners.forEach((fn) => {
    try {
      fn(state);
    } catch {
      // 구독자 예외가 소켓 처리를 막지 않게 한다
    }
  });
}

function clearRetry() {
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
}

function scheduleReconnect() {
  if (manuallyClosed || retryTimer) return;

  const delay = RETRY_DELAYS[Math.min(retryIndex, RETRY_DELAYS.length - 1)];
  retryIndex += 1;

  console.log(`[WS] ${delay}ms 후 재연결 시도`);
  retryTimer = setTimeout(() => {
    retryTimer = null;
    open().catch(() => scheduleReconnect());
  }, delay);
}

/**
 * 접속 URL 에 로컬 세션 토큰을 붙인다.
 *
 * 서버는 WebSocket 접속에도 토큰을 요구한다. 브라우저 WebSocket API 로는 헤더를 붙일 수
 * 없어서 쿼리로 보낸다. 토큰은 Electron 메인 프로세스가 파일에서 읽어 IPC 로 넘겨준다.
 * (HTTP 요청은 프록시가 헤더로 붙이므로 렌더러가 토큰을 알 필요가 없다)
 */
async function buildUrl() {
  try {
    const token = await window.managerWin?.getWsToken?.();
    if (!token) return url;
    const u = new URL(url);
    u.searchParams.set("token", token);
    return u.toString();
  } catch {
    return url; // 토큰을 못 구하면 그대로 시도한다(인증이 꺼진 환경일 수 있다)
  }
}

async function open() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return ws;
  }

  ws = new WebSocket(await buildUrl());

  ws.onopen = () => {
    retryIndex = 0;
    console.log("[WS] connected");
    notifyState({ connected: true });
  };

  ws.onclose = () => {
    console.log("[WS] closed");
    notifyState({ connected: false });
    scheduleReconnect();
  };

  ws.onerror = (e) => {
    // onerror 뒤에는 onclose 가 이어지므로 재연결 예약은 거기서만 한다.
    console.log("[WS] error", e);
  };

  ws.onmessage = (evt) => {
    let data;
    try {
      data = JSON.parse(evt.data);
    } catch {
      return; // JSON 이 아닌 메시지는 무시
    }

    listeners.forEach((fn) => {
      try {
        fn(data);
      } catch {
        // 한 구독자의 예외가 나머지 구독자를 막지 않게 한다
      }
    });
  };

  return ws;
}

export function connectAgentWs(nextUrl = DEFAULT_URL) {
  url = nextUrl || DEFAULT_URL;
  manuallyClosed = false;
  return open().catch((e) => {
    console.warn("[WS] 접속 실패", e);
    scheduleReconnect();
    return null;
  });
}

/** WS 메시지 구독. 반환값을 호출하면 구독 해제. */
export function addAgentWsListener(fn) {
  if (typeof fn !== "function") return () => {};
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** 연결 상태 구독(연결/끊김 표시용). */
export function addAgentWsStateListener(fn) {
  if (typeof fn !== "function") return () => {};
  stateListeners.add(fn);
  // 현재 상태를 즉시 한 번 알려준다.
  try {
    fn({ connected: !!ws && ws.readyState === WebSocket.OPEN });
  } catch {
    // 무시
  }
  return () => stateListeners.delete(fn);
}

export function isAgentWsConnected() {
  return !!ws && ws.readyState === WebSocket.OPEN;
}

export function closeAgentWs() {
  manuallyClosed = true;
  clearRetry();
  retryIndex = 0;
  try {
    ws?.close?.();
  } catch {
    // 이미 닫힌 소켓은 무시
  }
  ws = undefined;
}

// sendToAgent / setModeVKey 는 제거했다.
// /ws/ui 는 수신 전용 채널이고(서버가 이 소켓의 입력을 처리하지 않는다),
// 명령은 전부 REST(/api/control/*)로 보낸다. 둘 다 호출하는 곳이 없는 죽은 코드였다.
