import json
import time
from websocket import WebSocketApp

WS_URL = "ws://127.0.0.1:8080/ws/agent"

enabled = False
mode = "MOUSE"
locked = True

def on_open(ws):
    print("[PY] connected")

    def loop():
        while True:
            ws.send(json.dumps({
                "type": "STATUS",
                "enabled": enabled,
                "mode": mode,
                "locked": locked,
                "gesture": "NONE",
                "fps": 30.0
            }))
            time.sleep(0.5)

    import threading
    threading.Thread(target=loop, daemon=True).start()

def on_message(ws, msg):
    global enabled, mode
    data = json.loads(msg)
    print("[PY] <= ", data)

    if data.get("type") == "ENABLE":
        enabled = True
    elif data.get("type") == "DISABLE":
        enabled = False
    elif data.get("type") == "SET_MODE":
        mode = data.get("mode", "MOUSE")

def on_close(ws, *args):
    print("[PY] closed")

ws = WebSocketApp(WS_URL, on_open=on_open, on_message=on_message, on_close=on_close)
ws.run_forever()
