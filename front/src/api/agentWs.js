// src/api/agentWs.js
// - Dev/Prod 모두 동작하도록 WS URL을 환경변수로 분리
// - 연결 재사용 + 리스너 브로드캐스트
// - (옵션) 필요 시 reconnect 유틸 제공

let ws;
const listeners = new Set();

// ✅ 빌드타임 환경변수(Vite)
//   - .env.development / .env.production 에서 설정 가능
//   - 없으면 기본값으로 127.0.0.1:8080 사용
const DEFAULT_WS_URL = "ws://127.0.0.1:8080/ws/agent";

// Vite 환경이 아닌 곳에서도(테스트 등) 터지지 않게 방어
function getEnvWsUrl() {
  try {
    // Vite: import.meta.env
    const v = import.meta?.env?.VITE_WS_URL;
    if (v && typeof v === "string") return v;
  } catch {}
  return DEFAULT_WS_URL;
}

let lastUrl = getEnvWsUrl();

// -----------------------------
// 내부 유틸
// -----------------------------
function _isAlive(sock) {
  return (
    sock &&
    (sock.readyState === WebSocket.OPEN || sock.readyState === WebSocket.CONNECTING)
  );
}

function _emitToListeners(data) {
  listeners.forEach((fn) => {
    try {
      fn(data);
    } catch {}
  });
}

// -----------------------------
// Public API
// -----------------------------
export function connectAgentWs(url = getEnvWsUrl()) {
  lastUrl = url;

  // 이미 연결돼 있으면 재사용
  if (_isAlive(ws)) return ws;

  ws = new WebSocket(url);

  ws.onopen = () => console.log("[WS] connected:", url);
  ws.onclose = () => console.log("[WS] closed");
  ws.onerror = (e) => console.log("[WS] error", e);

  ws.onmessage = (evt) => {
    try {
      const data = JSON.parse(evt.data);
      _emitToListeners(data);
    } catch {
      // non-json 무시
    }
  };

  return ws;
}

// ✅ 외부에서 WS 메시지 구독
export function addAgentWsListener(fn) {
  if (typeof fn !== "function") return () => {};
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function closeAgentWs() {
  try {
    ws?.close?.();
  } catch {}
  ws = undefined;
}

// 연결 상태 확인(필요하면 UI에서 표시)
export function getAgentWsState() {
  return ws?.readyState ?? WebSocket.CLOSED;
}

export function sendToAgent(obj) {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    console.warn("[WS] not open");
    return false;
  }
  try {
    ws.send(JSON.stringify(obj));
    return true;
  } catch (e) {
    console.warn("[WS] send failed", e);
    return false;
  }
}

// ✅ VKEY 선택하면 이거 호출
export function setModeVKey() {
  // 1) 보통 ENABLE 먼저 (프로젝트 정책에 따라)
  sendToAgent({ type: "ENABLE" });

  // 2) 모드 변경
  sendToAgent({ type: "SET_MODE", mode: "VKEY" });
}

/**
 * (옵션) 자동 재연결이 필요하면 이걸 써.
 * - 앱 시작 시 한 번 호출해두면, 끊겨도 주기적으로 재연결 시도 가능
 * - 반환값: stop() 함수
 */
export function startAgentWsAutoReconnect({
  url = getEnvWsUrl(),
  intervalMs = 1500,
} = {}) {
  lastUrl = url;
  let stopped = false;
  let timer = null;

  const tick = () => {
    if (stopped) return;
    try {
      if (!_isAlive(ws)) connectAgentWs(lastUrl);
    } catch {}
    timer = setTimeout(tick, intervalMs);
  };

  tick();

  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
    timer = null;
  };
}
