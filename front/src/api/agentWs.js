// src/api/agentWs.js
let ws;

export function connectAgentWs(url = "ws://127.0.0.1:8080/ws/agent") {
  ws = new WebSocket(url);

  ws.onopen = () => console.log("[WS] connected");
  ws.onclose = () => console.log("[WS] closed");
  ws.onerror = (e) => console.log("[WS] error", e);

  ws.onmessage = (evt) => {
    try {
      const data = JSON.parse(evt.data);
      // STATUS 수신해서 UI 갱신하는 용도(선택)
      // console.log("[WS] msg", data);
    } catch {}
  };

  return ws;
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
