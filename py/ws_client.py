import json
import time
import threading
import websocket  # websocket-client

WS_URL = "ws://127.0.0.1:8080/ws/agent"

# 에이전트 상태(너 기존 코드의 전역 상태/클래스 상태로 합쳐도 됨)
state = {
    "enabled": False,
    "mode": "MOUSE",
    "locked": False,
    "gesture": "NONE",
    "fps": 0.0,
    "scrollActive": False,
    "canMove": False,
    "canClick": False,
}

state_lock = threading.Lock()

def apply_command(cmd: dict):
    t = cmd.get("type")
    if t == "ENABLE":
        with state_lock:
            state["enabled"] = True
        print("[PY] ENABLE")
    elif t == "DISABLE":
        with state_lock:
            state["enabled"] = False
        print("[PY] DISABLE")
    elif t == "SET_MODE":
        m = cmd.get("mode") or "MOUSE"
        with state_lock:
            state["mode"] = m
        print(f"[PY] SET_MODE {m}")
    elif t == "UPDATE_SETTINGS":
        settings = cmd.get("settings") or {}
        print(f"[PY] UPDATE_SETTINGS {settings}")
        # TODO: settings를 네 에이전트 설정에 반영
    else:
        print(f"[PY] unknown type={t} cmd={cmd}")

def make_status_payload():
    with state_lock:
        snap = dict(state)
    snap["type"] = "STATUS"
    return snap

def status_sender(ws):
    # 5Hz로 STATUS 송신 (원하면 10Hz까지)
    while ws.keep_running:
        try:
            payload = make_status_payload()
            ws.send(json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            print("[PY] status send error:", e)
            break
        time.sleep(0.2)

def on_open(ws):
    print("[PY] WS connected")
    # 연결되자마자 1번 상태 보내기
    ws.send(json.dumps(make_status_payload(), ensure_ascii=False))
    # 주기 STATUS 쓰레드 시작
    threading.Thread(target=status_sender, args=(ws,), daemon=True).start()

def on_message(ws, message):
    try:
        cmd = json.loads(message)
        apply_command(cmd)
    except Exception as e:
        print("[PY] bad message:", message, e)

def on_close(ws, code, msg):
    print("[PY] WS closed", code, msg)

def on_error(ws, err):
    print("[PY] WS error:", err)

def run_forever():
    while True:
        try:
            ws = websocket.WebSocketApp(
                WS_URL,
                on_open=on_open,
                on_message=on_message,
                on_close=on_close,
                on_error=on_error,
            )
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as e:
            print("[PY] run_forever exception:", e)

        # 재연결 딜레이
        time.sleep(1)

if __name__ == "__main__":
    run_forever()
