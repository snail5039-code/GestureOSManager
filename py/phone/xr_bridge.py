# xr_bridge.py
import json
import socket
import time
import threading
from collections import deque

import pyautogui

# --------------------------
# Settings
# --------------------------
UDP_PORT = 39500
TIMEOUT_SEC = 0.35        # 최근 패킷 판단 (조금 여유)
TICK_HZ = 120             # 커서 업데이트 주기
SMOOTH = 0.35             # 0~1 (클수록 더 부드럽게/느리게)
CLICK_DEBOUNCE_SEC = 0.05 # 탭 중복 방지
RIGHT_DEBOUNCE_SEC = 0.25 # 우클릭 중복 방지

pyautogui.FAILSAFE = False

_latest = {
    "ts": 0.0,
    "tracking": False,
    "x": 0.5,
    "y": 0.5,
}

_state = {
    "dragging": False,
    "locked": False,
    "last_left": 0.0,
    "last_right": 0.0,
    "sx": None,
    "sy": None,
}

# ✅ 이벤트는 "마지막 값"이 아니라 큐로 쌓는다 (유실 방지)
_events = deque(maxlen=256)

_lock = threading.Lock()


def clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


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
            if msg.get("type") != "XR_INPUT":
                continue

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

                # ✅ NONE은 큐에 넣지 않는다
                if gesture and gesture != "NONE":
                    _events.append(gesture)

        except Exception:
            continue


def _pop_events():
    with _lock:
        if not _events:
            return []
        evs = list(_events)
        _events.clear()
        return evs


def apply_gesture(gesture: str):
    now = time.time()

    # LOCK 상태면: LOCK_TOGGLE만 허용
    if _state["locked"]:
        if gesture == "LOCK_TOGGLE":
            _state["locked"] = False
            print("[XR] LOCK -> OFF")
        return

    # unlocked 상태에서 LOCK_TOGGLE 처리
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


def main():
    stop_evt = threading.Event()
    th = threading.Thread(target=udp_listener, args=(stop_evt,), daemon=True)
    th.start()

    w, h = pyautogui.size()
    print(f"[XR] Screen: {w}x{h}")

    _state["sx"] = w * 0.5
    _state["sy"] = h * 0.5

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

            # 1) 이벤트 먼저 처리 (큐에 쌓인 것 전부)
            if recent:
                evs = _pop_events()
                for g in evs:
                    apply_gesture(g)

            # 2) move는 tracking+recent일 때만
            if recent and tracking and (not _state["locked"]):
                tx = x01 * (w - 1)
                ty = y01 * (h - 1)

                sx = _state["sx"] + (tx - _state["sx"]) * (1.0 - SMOOTH)
                sy = _state["sy"] + (ty - _state["sy"]) * (1.0 - SMOOTH)
                _state["sx"], _state["sy"] = sx, sy

                pyautogui.moveTo(sx, sy)

            time.sleep(tick_dt)

    except KeyboardInterrupt:
        print("\n[XR] stopping...")
    finally:
        stop_evt.set()


if __name__ == "__main__":
    main()
