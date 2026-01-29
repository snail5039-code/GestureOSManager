# file: py/gestureos_agent/win_inject.py
from __future__ import annotations

"""
Win11/64bit 안정형 입력 주입 유틸 (SendInput 통일)

목표:
- 마우스: down/up/click/wheel
- 키보드: press / hotkey (Alt+Tab, Ctrl+C 등)
- SendInput 실패 시 mouse_event로 fallback (mouse only)

주의:
- 키 입력은 SendInput(scancode)로만 처리(Win11에서 안정).
"""

import os
import ctypes
from ctypes import wintypes

_IS_WIN = (os.name == "nt")
INJECT_DEBUG = os.getenv("INJECT_DEBUG", "0").strip() in ("1", "true", "True", "YES", "yes")


def _dbg(*a):
    if INJECT_DEBUG:
        try:
            print("[INJECT]", *a, flush=True)
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Non-Windows fallback (dev only)
# -----------------------------------------------------------------------------
if not _IS_WIN:
    import pyautogui

    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0

    def mouse_left_down() -> bool:
        pyautogui.mouseDown(button="left")
        return True

    def mouse_left_up() -> bool:
        pyautogui.mouseUp(button="left")
        return True

    def mouse_right_down() -> bool:
        pyautogui.mouseDown(button="right")
        return True

    def mouse_right_up() -> bool:
        pyautogui.mouseUp(button="right")
        return True

    def mouse_left_click() -> bool:
        pyautogui.click(button="left")
        return True

    def mouse_wheel(delta: int) -> bool:
        pyautogui.scroll(int(delta))
        return True

    def key_press_name(name: str) -> bool:
        name = (name or "").lower()
        if name == "shift_tab":
            pyautogui.hotkey("shift", "tab")
        elif "+" in name:
            pyautogui.hotkey(*[x.strip() for x in name.split("+") if x.strip()])
        else:
            pyautogui.press(name)
        return True

    def hotkey(*names: str) -> bool:
        keys = [str(x).lower() for x in names if x]
        if keys:
            pyautogui.hotkey(*keys)
        return True


# -----------------------------------------------------------------------------
# Windows SendInput
# -----------------------------------------------------------------------------
else:
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    try:
        ULONG_PTR = wintypes.ULONG_PTR
    except AttributeError:
        ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32

    INPUT_MOUSE = 0
    INPUT_KEYBOARD = 1

    # Mouse flags
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_WHEEL = 0x0800

    # Keyboard flags
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_SCANCODE = 0x0008

    # VK table (필요한 것만)
    VK = {
        "BACKSPACE": 0x08,
        "TAB": 0x09,
        "ENTER": 0x0D,
        "RETURN": 0x0D,
        "SHIFT": 0x10,
        "CTRL": 0x11,
        "CONTROL": 0x11,
        "ALT": 0x12,
        "ESC": 0x1B,
        "ESCAPE": 0x1B,
        "SPACE": 0x20,
        "PAGEUP": 0x21,
        "PAGEDOWN": 0x22,
        "END": 0x23,
        "HOME": 0x24,
        "LEFT": 0x25,
        "UP": 0x26,
        "RIGHT": 0x27,
        "DOWN": 0x28,
        "INSERT": 0x2D,
        "DELETE": 0x2E,
        "F1": 0x70,
        "F2": 0x71,
        "F3": 0x72,
        "F4": 0x73,
        "F5": 0x74,
        "F6": 0x75,
        "F7": 0x76,
        "F8": 0x77,
        "F9": 0x78,
        "F10": 0x79,
        "F11": 0x7A,
        "F12": 0x7B,
    }

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

    class INPUT_UNION(ctypes.Union):
        _fields_ = [
            ("mi", MOUSEINPUT),
            ("ki", KEYBDINPUT),
            ("hi", HARDWAREINPUT),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [
            ("type", wintypes.DWORD),
            ("u", INPUT_UNION),
        ]

    # Prototypes (중요)
    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT

    user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
    user32.MapVirtualKeyW.restype = wintypes.UINT

    # fallback
    user32.mouse_event.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ULONG_PTR)
    user32.mouse_event.restype = None

    def _send_input(inp: INPUT) -> bool:
        arr = (INPUT * 1)(inp)
        sent = int(user32.SendInput(1, arr, ctypes.sizeof(INPUT)))
        ok = (sent == 1)
        if not ok:
            _dbg("SendInput FAIL last_error=", ctypes.get_last_error())
        return ok

    # ---------------- mouse ----------------
    def _mouse(flags: int, data: int = 0) -> bool:
        # 1) SendInput
        try:
            inp = INPUT(
                type=INPUT_MOUSE,
                u=INPUT_UNION(mi=MOUSEINPUT(0, 0, wintypes.DWORD(int(data)), wintypes.DWORD(int(flags)), 0, 0)),
            )
            if _send_input(inp):
                return True
        except Exception as e:
            _dbg("SendInput mouse exception", e)

        # 2) fallback: mouse_event
        try:
            user32.mouse_event(int(flags), 0, 0, int(data), 0)
            return True
        except Exception as e:
            _dbg("mouse_event exception", e)
            return False

    def mouse_left_down() -> bool:
        return _mouse(MOUSEEVENTF_LEFTDOWN, 0)

    def mouse_left_up() -> bool:
        return _mouse(MOUSEEVENTF_LEFTUP, 0)

    def mouse_right_down() -> bool:
        return _mouse(MOUSEEVENTF_RIGHTDOWN, 0)

    def mouse_right_up() -> bool:
        return _mouse(MOUSEEVENTF_RIGHTUP, 0)

    def mouse_left_click() -> bool:
        ok1 = mouse_left_down()
        ok2 = mouse_left_up()
        return bool(ok1 and ok2)

    def mouse_wheel(delta: int) -> bool:
        d = int(delta or 0)
        if d == 0:
            return True
        return _mouse(MOUSEEVENTF_WHEEL, d)

    # ---------------- keyboard ----------------
    def _vk_from_name(name: str) -> int | None:
        if not name:
            return None
        n = str(name).strip().upper()

        if n in VK:
            return VK[n]

        # single char
        if len(n) == 1:
            if ("A" <= n <= "Z") or ("0" <= n <= "9"):
                return ord(n)

        return None

    def _key_scancode(vk: int) -> int:
        # MAPVK_VK_TO_VSC = 0
        return int(user32.MapVirtualKeyW(int(vk), 0) & 0xFFFF)

    def _send_key_vk(vk: int, is_up: bool) -> bool:
        scan = _key_scancode(vk)
        if scan == 0:
            return False

        flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if is_up else 0)

        # Extended keys
        if vk in (
            VK["LEFT"], VK["UP"], VK["RIGHT"], VK["DOWN"],
            VK["INSERT"], VK["DELETE"], VK["HOME"], VK["END"],
            VK["PAGEUP"], VK["PAGEDOWN"],
        ):
            flags |= KEYEVENTF_EXTENDEDKEY

        inp = INPUT(type=INPUT_KEYBOARD, u=INPUT_UNION(ki=KEYBDINPUT(0, scan, flags, 0, 0)))
        return _send_input(inp)

    def key_down_name(name: str) -> bool:
        vk = _vk_from_name(name)
        if vk is None:
            return False
        return _send_key_vk(vk, False)

    def key_up_name(name: str) -> bool:
        vk = _vk_from_name(name)
        if vk is None:
            return False
        return _send_key_vk(vk, True)

    def hotkey(*names: str) -> bool:
        keys = [str(x).strip().upper() for x in names if x]
        if not keys:
            return True

        # press down in order, release reverse
        downs: list[int] = []
        ok = True
        for k in keys:
            vk = _vk_from_name(k)
            if vk is None:
                ok = False
                continue
            ok = ok and _send_key_vk(vk, False)
            downs.append(vk)

        for vk in reversed(downs):
            ok = ok and _send_key_vk(vk, True)

        return ok

    def key_press_name(name: str) -> bool:
        n = (name or "").strip().upper()
        if not n:
            return False

        # aliases
        if n == "SHIFT_TAB":
            return hotkey("SHIFT", "TAB")

        # allow "CTRL+S"
        if "+" in n:
            parts = [p.strip() for p in n.split("+") if p.strip()]
            return hotkey(*parts)

        vk = _vk_from_name(n)
        if vk is None:
            _dbg("key_press_name unknown:", name)
            return False

        ok1 = _send_key_vk(vk, False)
        ok2 = _send_key_vk(vk, True)
        return bool(ok1 and ok2)
