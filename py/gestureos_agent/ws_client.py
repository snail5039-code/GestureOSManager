import json
import threading
import time
from typing import Callable, Optional

from websocket import WebSocketApp

class WSClient:
    """
    Simple WS client wrapper.
    - runs WebSocketApp in a daemon thread
    - exposes .send_dict(payload)
    - calls on_command(dict) for incoming messages
    """
    def __init__(self, url: str, on_command: Callable[[dict], None], enabled: bool = True):
        self.url = url
        self.on_command = on_command
        self.enabled = enabled

        self._ws: Optional[WebSocketApp] = None
        self.connected = False

    def start(self):
        if not self.enabled:
            return

        def _loop():
            while True:
                try:
                    ws = WebSocketApp(
                        self.url,
                        on_open=self._on_open,
                        on_close=self._on_close,
                        on_error=self._on_error,
                        on_message=self._on_message,
                    )
                    self._ws = ws
                    ws.run_forever(ping_interval=20, ping_timeout=10)
                except Exception as e:
                    print("[PY] ws_loop exception:", e)
                time.sleep(1.0)

        threading.Thread(target=_loop, daemon=True).start()

    def _on_open(self, ws):
        self.connected = True
        print("[PY] WS connected")

    def _on_error(self, ws, err):
        print("[PY] WS error:", err)

    def _on_close(self, ws, status_code, msg):
        self.connected = False
        print("[PY] WS closed:", status_code, msg)

    def _on_message(self, ws, msg: str):
        try:
            data = json.loads(msg)
        except Exception:
            print("[PY] bad json from server:", msg)
            return
        try:
            self.on_command(data)
        except Exception as e:
            print("[PY] on_command error:", e)

    def send_dict(self, payload: dict):
        if not self.enabled or (self._ws is None) or (not self.connected):
            return
        try:
            self._ws.send(json.dumps(payload))
        except Exception as e:
            print("[PY] ws send error:", e)
