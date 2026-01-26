// src/api/agentWs.js
let ws;
const listeners = new Set();

export function connectAgentWs(url = "ws://127.0.0.1:8080/ws/agent") {
  // 이미 연결돼 있으면 재사용
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return ws;
  }

  ws = new WebSocket(url);

  ws.onopen = () => console.log("[WS] connected");
  ws.onclose = () => console.log("[WS] closed");
  ws.onerror = (e) => console.log("[WS] error", e);

  ws.onmessage = (evt) => {
    try {
      const data = JSON.parse(evt.data);

      // ✅ 구독자들에게 전달
      listeners.forEach((fn) => {
        try {
          fn(data);
        } catch {}
      });
    } catch {}
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
