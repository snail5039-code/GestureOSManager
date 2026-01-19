import json
import socket
import time
import threading
from collections import deque

import pyautogui

# ✅ 모니터 좌표 매핑용
import mss
import ctypes

# --------------------------
# Settings
# --------------------------
UDP_PORT = 39500
TIMEOUT_SEC = 0.35
TICK_HZ = 120
SMOOTH = 0.35
CLICK_DEBOUNCE_SEC = 0.06
RIGHT_DEBOUNCE_SEC = 0.25

# ✅ 스트림에서 캡처하는 모니터와 "동일"하게 맞춰라.
MONITOR_INDEX = 1  # 1=첫 모니터, 2=두번째...

pyautogui.FAILSAFE = False

_latest = {"ts": 0.0, "tracking": False, "x": 0.5, "y": 0.5}
_state = {"dragging": False, "locked": False, "last_left": 0.0, "last_right": 0.0, "sx": None, "sy": None}
_events = deque(maxlen=256)
_lock = threading.Lock()

def _set_dpi_awareness():
    # Windows DPI scaling 좌표 mismatch 방지
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

def clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))

def get_monitor_rect(monitor_index: int):
    """
    mss 기준:
      monitors[0] = 전체 가상스크린
      monitors[1] = 1번 모니터 ...
    """
    with mss.mss() as sct:
        mons = sct.monitors
        if monitor_index < 0 or monitor_index >= len(mons):
            monitor_index = 0
        m = mons[monitor_index]
        left = int(m["left"])
        top = int(m["top"])
        width = int(m["width"])
        height = int(m["height"])
        return left, top, width, height

def udp_listener(stop_evt: threading.Event):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    sock.settimeout(0.2)
    print(f"[XR] UDP listening on 0.0.0.0:{UDP_PORT}")

    while not stop_evt.is_set():
        try:
            data, _addr = sock.recvfrom(8192)
        except socket.timeout:
            continue
        except Exception:
            continue

        try:
            msg = json.loads(data.decode("utf-8", errors="ignore"))
            mtype = str(msg.get("type", "")).upper()

            if mtype == "XR_INPUT":
                x = msg.get("pointerX", None)
                y = msg.get("pointerY", None)
                tracking = bool(msg.get("tracking", True))
                gesture = str(msg.get("gesture", "NONE")).upper()

                with _lock:
                    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                        _latest["x"] = clamp01(float(x))
                        _latest["y"] = clamp01(float(y))
                    _latest["tracking"] = tracking
                    _latest["ts"] = time.time()

                    if gesture and gesture != "NONE":
                        _events.append({"kind": "GESTURE", "gesture": gesture})
                continue

            if mtype == "XR_TEXT":
                text = str(msg.get("text", ""))
                if text:
                    with _lock:
                        _events.append({"kind": "TEXT", "text": text})
                continue

            if mtype == "XR_KEY":
                key = str(msg.get("key", "")).upper()
                action = str(msg.get("action", "TAP")).upper()
                if key:
                    with _lock:
                        _events.append({"kind": "KEY", "key": key, "action": action})
                continue

        except Exception:
            continue

def _pop_events():
    with _lock:
        if not _events:
            return []
        evs = list(_events)
        _events.clear()
        return evs

def _map_key_to_pyautogui(key: str) -> str:
    k = (key or "").upper()
    table = {
        "ENTER": "enter",
        "RETURN": "enter",
        "SPACE": "space",
        "BACKSPACE": "backspace",
        "TAB": "tab",
        "ESC": "esc",
        "ESCAPE": "esc",
        "LEFT": "left",
        "RIGHT": "right",
        "UP": "up",
        "DOWN": "down",
    }
    if k in table:
        return table[k]
    if isinstance(key, str) and len(key) == 1:
        return key
    return (key or "").lower()

def apply_gesture(gesture: str):
    now = time.time()

    if _state["locked"]:
        if gesture == "LOCK_TOGGLE":
            _state["locked"] = False
            print("[XR] LOCK -> OFF")
        return

    if gesture == "LOCK_TOGGLE":
        _state["locked"] = True
        print("[XR] LOCK -> ON")
        return

    if gesture == "PINCH_TAP":
        if (now - _state["last_left"] >= CLICK_DEBOUNCE_SEC) and (not _state["dragging"]):
            pyautogui.click()
            _state["last_left"] = now
        return

    if gesture == "PINCH_HOLD":
        if not _state["dragging"]:
            pyautogui.mouseDown()
            _state["dragging"] = True
        return

    if gesture == "PINCH_RELEASE":
        if _state["dragging"]:
            pyautogui.mouseUp()
            _state["dragging"] = False
        return

    if gesture == "RIGHT_CLICK":
        if (now - _state["last_right"] >= RIGHT_DEBOUNCE_SEC) and (not _state["dragging"]):
            pyautogui.click(button="right")
            _state["last_right"] = now
        return

def apply_event(ev: dict):
    kind = ev.get("kind")

    if kind == "GESTURE":
        apply_gesture(str(ev.get("gesture", "")).upper())
        return

    if kind == "TEXT":
        text = ev.get("text", "")
        if text:
            pyautogui.typewrite(text, interval=0)
        return

    if kind == "KEY":
        key = _map_key_to_pyautogui(ev.get("key", ""))
        action = str(ev.get("action", "TAP")).upper()
        if action == "TAP" and key:
            pyautogui.press(key)
        return

def main():
    _set_dpi_awareness()

    # ✅ 스트림 모니터 기준 좌표계
    left, top, mw, mh = get_monitor_rect(MONITOR_INDEX)
    print(f"[XR] Monitor#{MONITOR_INDEX} rect = left={left}, top={top}, w={mw}, h={mh}")

    stop_evt = threading.Event()
    th = threading.Thread(target=udp_listener, args=(stop_evt,), daemon=True)
    th.start()

    # smoothing 초기값: 모니터 중앙
    _state["sx"] = left + mw * 0.5
    _state["sy"] = top + mh * 0.5

    tick_dt = 1.0 / float(TICK_HZ)

    try:
        while True:
            now = time.time()

            with _lock:
                ts = _latest["ts"]
                tracking = bool(_latest["tracking"])
                x01 = float(_latest["x"])
                y01 = float(_latest["y"])

            recent = (now - ts <= TIMEOUT_SEC)

            # 1) 이벤트 처리
            evs = _pop_events()
            for ev in evs:
                apply_event(ev)

            # 2) move: recent+tracking+unlocked
            if recent and tracking and (not _state["locked"]):
                tx = left + x01 * (mw - 1)
                ty = top  + y01 * (mh - 1)

                # 1차 클램프: 목표좌표가 모니터 밖으로 튀는 것 방지
                tx = max(left, min(left + mw - 1, tx))
                ty = max(top,  min(top  + mh - 1, ty))

                sx = _state["sx"] + (tx - _state["sx"]) * (1.0 - SMOOTH)
                sy = _state["sy"] + (ty - _state["sy"]) * (1.0 - SMOOTH)

                # 2차 클램프: 스무딩 결과도 모니터 밖으로 못 나가게
                sx = max(left, min(left + mw - 1, sx))
                sy = max(top,  min(top  + mh - 1, sy))

                _state["sx"], _state["sy"] = sx, sy
                pyautogui.moveTo(sx, sy)


            time.sleep(tick_dt)

    except KeyboardInterrupt:
        print("\n[XR] stopping...")
    finally:
        stop_evt.set()

if __name__ == "__main__":
    main()
