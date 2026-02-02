// src/api/agentWs.js
import { wsUrl } from "../runtime/endpoints";

let ws;
const listeners = new Set();

export function connectAgentWs(url = wsUrl("/ws/hud")) {
  // 이미 연결돼 있으면 재사용
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return ws;
  }

  ws = new WebSocket(url);

  ws.onopen = () => console.log("[WS] connected", url);
  ws.onclose = () => console.log("[WS] closed");
  ws.onerror = (e) => console.log("[WS] error", e);

  ws.onmessage = (evt) => {
    try {
      const data = JSON.parse(evt.data);
      listeners.forEach((fn) => {
        try { fn(data); } catch {}
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
  try { ws?.close?.(); } catch {}
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
  sendToAgent({ type: "ENABLE" });
  sendToAgent({ type: "SET_MODE", mode: "VKEY" });
}
