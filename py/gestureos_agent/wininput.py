# py/gestureos_agent/wininput.py
# Centralized Win32 SendInput structures + helpers.
#
# Why this exists:
# - In this repo, several modules defined their own ctypes INPUT/UNION with only
#   the fields they needed (e.g., only MOUSEINPUT). That makes ctypes.sizeof(INPUT)
#   smaller than Windows expects, which can cause SendInput to fail with
#   ERROR_INVALID_PARAMETER (87), especially in PyInstaller builds.
# - Also, some call sites passed ctypes.byref(array) instead of passing the
#   array pointer itself.
#
# Fix:
# - Define the full INPUT union (MOUSEINPUT / KEYBDINPUT / HARDWAREINPUT) once.
# - Provide tiny wrappers that always call SendInput with the correct cbSize and
#   pointer type.

from __future__ import annotations

import os
import ctypes
from ctypes import wintypes

_IS_WIN = (os.name == "nt")

WININPUT_DEBUG = os.getenv("GESTUREOS_WININPUT_DEBUG", "0").strip() in (
    "1", "true", "True", "YES", "yes"
)


def _dlog(*a):
    if not WININPUT_DEBUG:
        return
    try:
        print("[WININPUT]", *a, flush=True)
    except Exception:
        pass


if _IS_WIN:
    # Load user32 with last-error support so ctypes.get_last_error() works.
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    # wintypes.ULONG_PTR isn't always present.
    try:
        ULONG_PTR = wintypes.ULONG_PTR
    except AttributeError:
        ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32

    # INPUT types
    INPUT_MOUSE = 0
    INPUT_KEYBOARD = 1
    INPUT_HARDWARE = 2

    # Mouse flags
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_MIDDLEDOWN = 0x0020
    MOUSEEVENTF_MIDDLEUP = 0x0040
    MOUSEEVENTF_WHEEL = 0x0800
    MOUSEEVENTF_ABSOLUTE = 0x8000
    MOUSEEVENTF_VIRTUALDESK = 0x4000

    WHEEL_DELTA = 120

    # Keyboard flags
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_SCANCODE = 0x0008

    MAPVK_VK_TO_VSC = 0

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
        _fields_ = [("type", wintypes.DWORD), ("u", INPUT_UNION)]

    LPINPUT = ctypes.POINTER(INPUT)

    user32.SendInput.argtypes = (wintypes.UINT, LPINPUT, ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT

    user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
    user32.MapVirtualKeyW.restype = wintypes.UINT

    # mouse_event fallback
    user32.mouse_event.argtypes = (wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ULONG_PTR)
    user32.mouse_event.restype = None


    def send_inputs(arr) -> int:
        """Call SendInput correctly.

        arr must be a ctypes array of INPUT: (INPUT * N)(...).
        Returns number of events successfully inserted.
        """
        try:
            n = int(user32.SendInput(len(arr), arr, ctypes.sizeof(INPUT)))
            if n != len(arr):
                err = ctypes.get_last_error()
                _dlog(f"SendInput partial/failed sent={n} need={len(arr)} last_error={err} cbSize={ctypes.sizeof(INPUT)}")
            return n
        except Exception as e:
            _dlog("SendInput exception", repr(e))
            return 0


    def _mouse_event_fallback(flags: int, data: int = 0) -> bool:
        try:
            user32.mouse_event(int(flags), 0, 0, int(data), 0)
            return True
        except Exception:
            return False


    def send_mouse(flags: int, data: int = 0) -> bool:
        """Send a mouse event (down/up/wheel) using SendInput; fallback to mouse_event."""
        inp = INPUT(type=INPUT_MOUSE)
        inp.u.mi = MOUSEINPUT(0, 0, int(data), int(flags), 0, 0)
        arr = (INPUT * 1)(inp)
        if send_inputs(arr) == 1:
            return True
        return _mouse_event_fallback(flags, data)


    def left_click() -> bool:
        down = INPUT(type=INPUT_MOUSE)
        down.u.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0)
        up = INPUT(type=INPUT_MOUSE)
        up.u.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0)
        arr = (INPUT * 2)(down, up)
        if send_inputs(arr) == 2:
            return True
        # fallback
        _mouse_event_fallback(MOUSEEVENTF_LEFTDOWN, 0)
        _mouse_event_fallback(MOUSEEVENTF_LEFTUP, 0)
        return True


    def left_down() -> bool:
        return send_mouse(MOUSEEVENTF_LEFTDOWN, 0)


    def left_up() -> bool:
        return send_mouse(MOUSEEVENTF_LEFTUP, 0)


    def right_click() -> bool:
        down = INPUT(type=INPUT_MOUSE)
        down.u.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_RIGHTDOWN, 0, 0)
        up = INPUT(type=INPUT_MOUSE)
        up.u.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_RIGHTUP, 0, 0)
        arr = (INPUT * 2)(down, up)
        if send_inputs(arr) == 2:
            return True
        _mouse_event_fallback(MOUSEEVENTF_RIGHTDOWN, 0)
        _mouse_event_fallback(MOUSEEVENTF_RIGHTUP, 0)
        return True


    def wheel(delta: int) -> bool:
        return send_mouse(MOUSEEVENTF_WHEEL, int(delta))


    def send_vk(vk_code: int):
        """Send a key press using scancode-first strategy."""
        vk_code = int(vk_code)
        is_extended = vk_code in (0x25, 0x26, 0x27, 0x28)  # arrows

        scan = int(user32.MapVirtualKeyW(vk_code, MAPVK_VK_TO_VSC)) & 0xFFFF
        if scan:
            flags_down = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if is_extended else 0)
            flags_up = flags_down | KEYEVENTF_KEYUP

            inp_down = INPUT(type=INPUT_KEYBOARD)
            inp_down.u.ki = KEYBDINPUT(0, scan, flags_down, 0, 0)

            inp_up = INPUT(type=INPUT_KEYBOARD)
            inp_up.u.ki = KEYBDINPUT(0, scan, flags_up, 0, 0)

            arr = (INPUT * 2)(inp_down, inp_up)
            send_inputs(arr)
            return

        # fallback: wVk
        flags_down = (KEYEVENTF_EXTENDEDKEY if is_extended else 0)
        flags_up = flags_down | KEYEVENTF_KEYUP

        inp_down = INPUT(type=INPUT_KEYBOARD)
        inp_down.u.ki = KEYBDINPUT(vk_code, 0, flags_down, 0, 0)

        inp_up = INPUT(type=INPUT_KEYBOARD)
        inp_up.u.ki = KEYBDINPUT(vk_code, 0, flags_up, 0, 0)

        arr = (INPUT * 2)(inp_down, inp_up)
        send_inputs(arr)

else:
    # Non-Windows stubs
    def send_inputs(arr):
        return 0

    def send_mouse(flags: int, data: int = 0) -> bool:
        return False

    def left_click() -> bool:
        return False

    def left_down() -> bool:
        return False

    def left_up() -> bool:
        return False

    def right_click() -> bool:
        return False

    def wheel(delta: int) -> bool:
        return False

    def send_vk(vk_code: int):
        return
