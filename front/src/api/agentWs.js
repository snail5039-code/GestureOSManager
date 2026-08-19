// src/api/agentWs.js
//
// 매니저 UI 가 에이전트 이벤트(APP_START / APP_STOP 같은 제스처 트리거)를 받는 통로.
//
// 예전에는 onclose 에서 로그만 찍고 끝이라, Spring 을 재시작하거나 잠깐 끊기면
// 앱을 다시 켤 때까지 제스처 이벤트가 오지 않았다. 파이썬 에이전트 쪽에는 1초 간격
// 재접속 루프가 있어서 양쪽이 비대칭이었다.

const DEFAULT_URL = "ws://127.0.0.1:8080/ws/agent";

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
    open();
  }, delay);
}

function open() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return ws;
  }

  ws = new WebSocket(url);

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
  return open();
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

export function sendToAgent(obj) {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    console.warn("[WS] not open");
    return false;
  }
  ws.send(JSON.stringify(obj));
  return true;
}

// ✅ VKEY 선택하면 이거 호출
export function setModeVKey() {
  // 1) 보통 ENABLE 먼저 (프로젝트 정책에 따라)
  sendToAgent({ type: "ENABLE" });

  // 2) 모드 변경
  sendToAgent({ type: "SET_MODE", mode: "VKEY" });
}
