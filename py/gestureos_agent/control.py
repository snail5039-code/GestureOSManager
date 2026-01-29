# py/gestureos_agent/control.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import os
import ctypes

import pyautogui

from .mathutil import clamp01

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0
pyautogui.MINIMUM_DURATION = 0
pyautogui.MINIMUM_SLEEP = 0

_IS_WIN = (os.name == "nt")


# =============================================================================
# ✅ DRAW pen-hold shared state (no new files)
# =============================================================================
_PEN_DOWN = False

def set_pen_down(v: bool) -> None:
    global _PEN_DOWN
    _PEN_DOWN = bool(v)

def is_pen_down() -> bool:
    return bool(_PEN_DOWN)


# =============================================================================
# Win32 mouse move: SendInput(ABS+VIRTUALDESK) + fallback(SetCursorPos)
# =============================================================================
if _IS_WIN:
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    try:
        ULONG_PTR = wintypes.ULONG_PTR
    except AttributeError:
        ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32

    INPUT_MOUSE = 0

    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_ABSOLUTE = 0x8000
    MOUSEEVENTF_VIRTUALDESK = 0x4000

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]

    class _POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
    user32.SetCursorPos.restype = wintypes.BOOL

    user32.GetCursorPos.argtypes = (ctypes.POINTER(_POINT),)
    user32.GetCursorPos.restype = wintypes.BOOL

    user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
    user32.GetSystemMetrics.restype = ctypes.c_int

    user32.SendInput.argtypes = (wintypes.UINT, ctypes.c_void_p, ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT

    def _get_cursor_xy() -> Tuple[int, int]:
        pt = _POINT()
        ok = user32.GetCursorPos(ctypes.byref(pt))
        if not ok:
            return (0, 0)
        return (int(pt.x), int(pt.y))

    def _virtual_screen_rect() -> Tuple[int, int, int, int]:
        SM_XVIRTUALSCREEN = 76
        SM_YVIRTUALSCREEN = 77
        SM_CXVIRTUALSCREEN = 78
        SM_CYVIRTUALSCREEN = 79
        vx = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
        vy = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
        vw = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
        vh = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
        vw = max(1, vw)
        vh = max(1, vh)
        return (vx, vy, vw, vh)

    def _setcursorpos_move(x: int, y: int) -> bool:
        vx, vy, vw, vh = _virtual_screen_rect()
        x = max(vx, min(vx + vw - 1, int(x)))
        y = max(vy, min(vy + vh - 1, int(y)))
        return bool(user32.SetCursorPos(int(x), int(y)))

    def _sendinput_move_abs_virtual(x: int, y: int) -> bool:
        vx, vy, vw, vh = _virtual_screen_rect()
        x = max(vx, min(vx + vw - 1, int(x)))
        y = max(vy, min(vy + vh - 1, int(y)))

        denom_x = max(1, vw - 1)
        denom_y = max(1, vh - 1)
        ax = int((x - vx) * 65535 / denom_x)
        ay = int((y - vy) * 65535 / denom_y)

        mi = _MOUSEINPUT(
            dx=ax,
            dy=ay,
            mouseData=0,
            dwFlags=(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK),
            time=0,
            dwExtraInfo=0,
        )
        inp = _INPUT(type=INPUT_MOUSE, u=_INPUT_UNION(mi=mi))

        try:
            n = int(user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT)))
            return (n == 1)
        except Exception:
            return False


# env: windows move mode (default: sendinput then fallback)
_WIN_MOVE_MODE = os.getenv("GESTUREOS_WIN_MOVE", "sendinput").strip().lower()

# ✅ DRAW 중엔 "스킵" 최대한 줄이기 위한 튜닝(환경변수로 조절 가능)
_DRAW_MOVE_INTERVAL_SEC = float(os.getenv("GESTUREOS_DRAW_MOVE_INTERVAL", "0.004"))  # 4ms
_DRAW_DEADZONE_PX = float(os.getenv("GESTUREOS_DRAW_DEADZONE_PX", "0.0"))            # 0px


@dataclass
class ControlMapper:
    control_box: Tuple[float, float, float, float]
    gain: float
    ema_alpha: float
    deadzone_px: int
    move_interval_sec: float

    ema_x: Optional[float] = None
    ema_y: Optional[float] = None
    last_move_ts: float = 0.0

    def reset_ema(self):
        self.ema_x = None
        self.ema_y = None

    def set_gain(self, g: float):
        self.gain = float(g)

    def map_control_to_screen(self, cx: float, cy: float) -> Tuple[float, float]:
        minx, miny, maxx, maxy = self.control_box
        ux = (cx - minx) / max(1e-6, (maxx - minx))
        uy = (cy - miny) / max(1e-6, (maxy - miny))
        ux = clamp01(ux)
        uy = clamp01(uy)

        ux = 0.5 + (ux - 0.5) * self.gain
        uy = 0.5 + (uy - 0.5) * self.gain
        return clamp01(ux), clamp01(uy)

    def apply_ema(self, nx: float, ny: float) -> Tuple[float, float]:
        if self.ema_x is None:
            self.ema_x, self.ema_y = nx, ny
        else:
            a = self.ema_alpha
            self.ema_x = a * nx + (1.0 - a) * self.ema_x
            self.ema_y = a * ny + (1.0 - a) * self.ema_y
        return self.ema_x, self.ema_y

    def move_cursor(self, norm_x: float, norm_y: float, now_ts: float):
        # ✅ DRAW(펜 홀드) 중에는 throttle/deadzone을 강제로 낮추고, SendInput 우선
        interval = float(self.move_interval_sec)
        dz = float(self.deadzone_px)
        pen = is_pen_down()
        if pen:
            interval = _DRAW_MOVE_INTERVAL_SEC
            dz = _DRAW_DEADZONE_PX

        if (now_ts - self.last_move_ts) < interval:
            return
        self.last_move_ts = now_ts

        if _IS_WIN:
            vx, vy, vw, vh = _virtual_screen_rect()
            x = int(vx + clamp01(norm_x) * max(1, (vw - 1)))
            y = int(vy + clamp01(norm_y) * max(1, (vh - 1)))
            x = max(vx, min(vx + vw - 1, x))
            y = max(vy, min(vy + vh - 1, y))

            # deadzone (DRAW 중엔 0이라 거의 안 걸림)
            cx, cy = _get_cursor_xy()
            if abs(x - cx) < dz and abs(y - cy) < dz:
                return

            # DRAW 중에는 SendInput을 최대한 유지(드래그 캔버스에서 SetCursorPos로 튀는 케이스 방지)
            if pen:
                _sendinput_move_abs_virtual(x, y)
                return

            if _WIN_MOVE_MODE == "setcursorpos":
                _setcursorpos_move(x, y)
                return

            ok = _sendinput_move_abs_virtual(x, y)
            if not ok:
                _setcursorpos_move(x, y)
            return

        # non-windows fallback
        sx, sy = pyautogui.size()
        x = int(clamp01(norm_x) * sx)
        y = int(clamp01(norm_y) * sy)
        cur = pyautogui.position()
        if abs(x - cur.x) < int(self.deadzone_px) and abs(y - cur.y) < int(self.deadzone_px):
            return
        pyautogui.moveTo(x, y, _pause=False)
