# xr_bridge.py (FINAL)
import json
import socket
import time
import threading
from collections import deque

import ctypes
from ctypes import wintypes

import mss

# =========================
# CONFIG
# =========================
UDP_PORT = 39500
TIMEOUT_SEC = 0.35
TICK_HZ = 120

SMOOTH = 0.35
CLICK_DEBOUNCE_SEC = 0.06
RIGHT_DEBOUNCE_SEC = 0.25

MONITOR_INDEX = 1            # 1=첫 모니터 (mss 기준)
WARP_ON_CLICK = True
WARP_ON_KEY_CLICK = True
CLICK_WARP_DELAY_SEC = 0.004
DRAG_AUTORELEASE_SEC = 0.9

DEBUG = False

# =========================
# STATE
# =========================
_latest = {"ts": 0.0, "tracking": False, "x": 0.5, "y": 0.5}
_state = {
    "dragging": False,
    "locked": False,
    "last_left": 0.0,
    "last_right": 0.0,
    "sx": None,
    "sy": None,
}
_events = deque(maxlen=512)
_lock = threading.Lock()


# =========================
# DPI AWARE
# =========================
def _set_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor DPI aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def get_monitor_rect(monitor_index: int):
    with mss.mss() as sct:
        mons = sct.monitors
        if monitor_index < 0 or monitor_index >= len(mons):
            monitor_index = 0
        m = mons[monitor_index]
        return int(m["left"]), int(m["top"]), int(m["width"]), int(m["height"])


# =========================
# Win32 SendInput (mouse + key)
# =========================
user32 = ctypes.windll.user32

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_UNICODE = 0x0004

# IME / modifiers
VK_HANGUL = 0x15
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4     # ALT
VK_RMENU = 0xA5
VK_LWIN = 0x5B
VK_RWIN = 0x5C

# common keys
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # ALT
VK_RETURN = 0x0D
VK_SPACE = 0x20
VK_BACK = 0x08
VK_TAB = 0x09
VK_ESCAPE = 0x1B
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28


ULONG_PTR = wintypes.WPARAM


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


def _send_input(*inputs: INPUT):
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(arr), ctypes.byref(arr), ctypes.sizeof(INPUT))


def _virtual_screen_rect():
    left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return int(left), int(top), int(w), int(h)


def _mouse_abs_xy(x: float, y: float):
    vleft, vtop, vw, vh = _virtual_screen_rect()
    if vw <= 1: vw = 2
    if vh <= 1: vh = 2
    ax = int(round((x - vleft) * 65535.0 / (vw - 1)))
    ay = int(round((y - vtop) * 65535.0 / (vh - 1)))
    ax = max(0, min(65535, ax))
    ay = max(0, min(65535, ay))
    return ax, ay


def mouse_move_to(x: float, y: float):
    ax, ay = _mouse_abs_xy(x, y)
    inp = INPUT(
        type=INPUT_MOUSE,
        union=_INPUTUNION(
            mi=MOUSEINPUT(
                dx=ax,
                dy=ay,
                mouseData=0,
                dwFlags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                time=0,
                dwExtraInfo=0,
            )
        ),
    )
    _send_input(inp)


def mouse_left_down():
    inp = INPUT(type=INPUT_MOUSE, union=_INPUTUNION(
        mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0)
    ))
    _send_input(inp)


def mouse_left_up():
    inp = INPUT(type=INPUT_MOUSE, union=_INPUTUNION(
        mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0)
    ))
    _send_input(inp)


def mouse_left_click():
    down = INPUT(type=INPUT_MOUSE, union=_INPUTUNION(
        mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0)
    ))
    up = INPUT(type=INPUT_MOUSE, union=_INPUTUNION(
        mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0)
    ))
    _send_input(down, up)


def mouse_right_click():
    down = INPUT(type=INPUT_MOUSE, union=_INPUTUNION(
        mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_RIGHTDOWN, 0, 0)
    ))
    up = INPUT(type=INPUT_MOUSE, union=_INPUTUNION(
        mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_RIGHTUP, 0, 0)
    ))
    _send_input(down, up)


# ---- keyboard helpers ----
def _key_vk(name: str):
    k = (name or "").strip().lower()
    extended = False

    table = {
        "shift": VK_SHIFT,
        "ctrl": VK_CONTROL, "control": VK_CONTROL,
        "alt": VK_MENU,
        "enter": VK_RETURN, "return": VK_RETURN,
        "space": VK_SPACE,
        "backspace": VK_BACK, "bs": VK_BACK,
        "tab": VK_TAB,
        "esc": VK_ESCAPE, "escape": VK_ESCAPE,
        "left": VK_LEFT,
        "up": VK_UP,
        "right": VK_RIGHT,
        "down": VK_DOWN,
    }
    if k in table:
        vk = table[k]
        if vk in (VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN):
            extended = True
        return vk, extended

    # letters/digits as VK
    if len(k) == 1:
        ch = k
        if "a" <= ch <= "z":
            return ord(ch.upper()), False
        if "0" <= ch <= "9":
            return ord(ch), False

    return None, False


def _key_down_vk(vk: int, extended: bool = False):
    scan = user32.MapVirtualKeyW(vk, 0)
    flags = (KEYEVENTF_EXTENDEDKEY if extended else 0)
    inp = INPUT(type=INPUT_KEYBOARD, union=_INPUTUNION(
        ki=KEYBDINPUT(vk, scan, flags, 0, 0)
    ))
    _send_input(inp)


def _key_up_vk(vk: int, extended: bool = False):
    scan = user32.MapVirtualKeyW(vk, 0)
    flags = KEYEVENTF_KEYUP | (KEYEVENTF_EXTENDEDKEY if extended else 0)
    inp = INPUT(type=INPUT_KEYBOARD, union=_INPUTUNION(
        ki=KEYBDINPUT(vk, scan, flags, 0, 0)
    ))
    _send_input(inp)


def key_tap(key: str) -> bool:
    vk, ext = _key_vk(key)
    if vk is None:
        return False
    _key_down_vk(vk, ext)
    _key_up_vk(vk, ext)
    return True


def hotkey(keys) -> bool:
    # keys: ["ctrl","v"] etc
    seq = []
    for k in keys:
        vk, ext = _key_vk(k)
        if vk is None:
            return False
        seq.append((vk, ext))

    # down
    for vk, ext in seq:
        _key_down_vk(vk, ext)
    # up reverse
    for vk, ext in reversed(seq):
        _key_up_vk(vk, ext)
    return True


def _release_modifiers():
    # 핵심: 단축키로 먹는 문제(s/f/r/y) 방지
    for vk in (VK_LCONTROL, VK_RCONTROL, VK_LMENU, VK_RMENU, VK_LSHIFT, VK_RSHIFT, VK_LWIN, VK_RWIN):
        _key_up_vk(vk)


def toggle_korean_ime():
    _release_modifiers()
    # VK_HANGUL은 extended 아님
    _key_down_vk(VK_HANGUL, False)
    _key_up_vk(VK_HANGUL, False)


def type_unicode(text: str):
    """
    KEYEVENTF_UNICODE로 문자 자체를 주입.
    Ctrl/Alt/Shift가 붙어 있어도 문자 입력은 그대로 들어감.
    """
    if not text:
        return

    # UTF-16LE code units로 보내면 BMP 밖 문자도 안전
    b = text.encode("utf-16-le")
    # 2바이트씩 code unit
    for i in range(0, len(b), 2):
        code_unit = b[i] | (b[i + 1] << 8)

        down = INPUT(type=INPUT_KEYBOARD, union=_INPUTUNION(
            ki=KEYBDINPUT(0, code_unit, KEYEVENTF_UNICODE, 0, 0)
        ))
        up = INPUT(type=INPUT_KEYBOARD, union=_INPUTUNION(
            ki=KEYBDINPUT(0, code_unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0)
        ))
        _send_input(down, up)


# =========================
# UDP listener
# =========================
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

                now = time.time()
                with _lock:
                    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                        _latest["x"] = clamp01(float(x))
                        _latest["y"] = clamp01(float(y))
                    _latest["tracking"] = tracking
                    _latest["ts"] = now

                    if gesture and gesture != "NONE":
                        _events.append({
                            "kind": "GESTURE",
                            "gesture": gesture,
                            "x01": float(_latest["x"]),
                            "y01": float(_latest["y"]),
                            "ts": now
                        })
                continue

            if mtype == "XR_TEXT":
                text = str(msg.get("text", ""))
                if text:
                    with _lock:
                        _events.append({
                            "kind": "TEXT",
                            "text": text,
                            "x01": float(_latest["x"]),
                            "y01": float(_latest["y"]),
                            "ts": time.time()
                        })
                continue

            if mtype == "XR_KEY":
                key = str(msg.get("key", "")).strip()
                action = str(msg.get("action", "TAP")).upper()
                if key:
                    with _lock:
                        _events.append({
                            "kind": "KEY",
                            "key": key,
                            "action": action,
                            "x01": float(_latest["x"]),
                            "y01": float(_latest["y"]),
                            "ts": time.time()
                        })
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


def _map_key_to_simple(key: str) -> str:
    k = (key or "").strip()
    ku = k.upper()

    table = {
        "ENTER": "enter",
        "RETURN": "enter",
        "SPACE": "space",
        "BACKSPACE": "backspace",
        "BS": "backspace",
        "TAB": "tab",
        "ESC": "esc",
        "ESCAPE": "esc",
        "LEFT": "left",
        "RIGHT": "right",
        "UP": "up",
        "DOWN": "down",
        "CTRL": "ctrl",
        "CONTROL": "ctrl",
        "ALT": "alt",
        "SHIFT": "shift",
        "WIN": "win",
    }
    if ku in table:
        return table[ku]
    if len(k) == 1:
        return k  # 여기서 lower 강제 안 함(원문 유지)
    return k.lower()


# =========================
# Input application
# =========================
def _xy01_to_screen(left, top, mw, mh, x01, y01):
    tx = left + float(x01) * (mw - 1)
    ty = top + float(y01) * (mh - 1)
    tx = max(left, min(left + mw - 1, tx))
    ty = max(top,  min(top  + mh - 1, ty))
    return tx, ty


def _warp_to_event_xy(left, top, mw, mh, ev):
    x01 = ev.get("x01", None)
    y01 = ev.get("y01", None)
    if isinstance(x01, (int, float)) and isinstance(y01, (int, float)):
        tx, ty = _xy01_to_screen(left, top, mw, mh, x01, y01)
        mouse_move_to(tx, ty)
        _state["sx"], _state["sy"] = tx, ty
        time.sleep(CLICK_WARP_DELAY_SEC)


def apply_gesture(left, top, mw, mh, gesture: str, ev=None):
    now = time.time()

    if _state["locked"]:
        if gesture == "LOCK_TOGGLE":
            _state["locked"] = False
            if DEBUG: print("[XR] LOCK -> OFF")
        return

    if gesture == "LOCK_TOGGLE":
        if _state["dragging"]:
            mouse_left_up()
            _state["dragging"] = False
        _state["locked"] = True
        if DEBUG: print("[XR] LOCK -> ON")
        return

    if gesture == "PINCH_TAP":
        if (now - _state["last_left"] >= CLICK_DEBOUNCE_SEC) and (not _state["dragging"]):
            if WARP_ON_CLICK and ev is not None:
                _warp_to_event_xy(left, top, mw, mh, ev)
            mouse_left_click()
            _state["last_left"] = now
        return

    if gesture == "PINCH_HOLD":
        if not _state["dragging"]:
            if WARP_ON_CLICK and ev is not None:
                _warp_to_event_xy(left, top, mw, mh, ev)
            mouse_left_down()
            _state["dragging"] = True
        return

    if gesture == "PINCH_RELEASE":
        if _state["dragging"]:
            mouse_left_up()
            _state["dragging"] = False
        return

    if gesture == "RIGHT_CLICK":
        if (now - _state["last_right"] >= RIGHT_DEBOUNCE_SEC) and (not _state["dragging"]):
            if WARP_ON_CLICK and ev is not None:
                _warp_to_event_xy(left, top, mw, mh, ev)
            mouse_right_click()
            _state["last_right"] = now
        return


def apply_event(left, top, mw, mh, ev: dict):
    kind = ev.get("kind")

    if kind == "GESTURE":
        apply_gesture(left, top, mw, mh, str(ev.get("gesture", "")).upper(), ev=ev)
        return

    if kind == "TEXT":
        text = ev.get("text", "")
        if text:
            if WARP_ON_KEY_CLICK:
                _warp_to_event_xy(left, top, mw, mh, ev)
            _release_modifiers()
            type_unicode(text)
        return

    if kind == "KEY":
        raw = str(ev.get("key", "")).strip()
        action = str(ev.get("action", "TAP")).upper()
        if action != "TAP" or not raw:
            return

        if DEBUG:
            print("[XR][KEY]", raw)

        # 포커스 클릭
        if raw.upper() == "CLICK":
            if WARP_ON_KEY_CLICK:
                _warp_to_event_xy(left, top, mw, mh, ev)
            mouse_left_click()
            return

        # 한/영 토글
        if raw.upper() in ("KOR_TOGGLE", "KOR", "ALT+SHIFT"):
            toggle_korean_ime()
            return

        # 조합키
        if "+" in raw:
            parts = [p.strip() for p in raw.split("+") if p.strip()]
            keys = [_map_key_to_simple(p) for p in parts]
            keys = [k.lower() for k in keys if k]
            if keys:
                _release_modifiers()
                hotkey(keys)
            return

        k = _map_key_to_simple(raw)

        # ✅ 핵심: 1글자면 유니코드 입력으로 처리 (s/f/r/y 포함 전부 확실히 들어감)
        if len(k) == 1:
            _release_modifiers()
            type_unicode(k)   # 그대로 입력
            return

        # 특수키는 VK 탭
        k2 = k.lower()
        if k2 in ("enter", "return", "space", "backspace", "tab", "esc", "escape", "left", "right", "up", "down"):
            _release_modifiers()
            key_tap(k2)
            return

        # 기타는 일단 유니코드로 처리(라벨 텍스트 그대로)
        _release_modifiers()
        type_unicode(k)
        return


# =========================
# MAIN LOOP
# =========================
def main():
    _set_dpi_awareness()

    left, top, mw, mh = get_monitor_rect(MONITOR_INDEX)
    print(f"[XR] Monitor#{MONITOR_INDEX} rect = left={left}, top={top}, w={mw}, h={mh}")

    stop_evt = threading.Event()
    th = threading.Thread(target=udp_listener, args=(stop_evt,), daemon=True)
    th.start()

    _state["sx"] = left + mw * 0.5
    _state["sy"] = top + mh * 0.5

    tick_dt = 1.0 / float(TICK_HZ)

    try:
        while True:
            now = time.time()

            with _lock:
                ts = float(_latest["ts"])
                tracking = bool(_latest["tracking"])
                x01 = float(_latest["x"])
                y01 = float(_latest["y"])

            recent = (now - ts <= TIMEOUT_SEC)

            for ev in _pop_events():
                apply_event(left, top, mw, mh, ev)

            # 트래킹 끊기면 드래그 자동 해제
            if _state["dragging"]:
                if (not recent) or (not tracking):
                    if (now - ts) > DRAG_AUTORELEASE_SEC:
                        mouse_left_up()
                        _state["dragging"] = False

            # 이동
            if recent and tracking and (not _state["locked"]):
                tx, ty = _xy01_to_screen(left, top, mw, mh, x01, y01)

                sx = _state["sx"] + (tx - _state["sx"]) * (1.0 - SMOOTH)
                sy = _state["sy"] + (ty - _state["sy"]) * (1.0 - SMOOTH)

                sx = max(left, min(left + mw - 1, sx))
                sy = max(top,  min(top  + mh - 1, sy))

                _state["sx"], _state["sy"] = sx, sy
                mouse_move_to(sx, sy)

            time.sleep(tick_dt)

    except KeyboardInterrupt:
        print("\n[XR] stopping...")
    finally:
        stop_evt.set()


if __name__ == "__main__":
    main()
