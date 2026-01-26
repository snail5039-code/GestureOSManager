# py/gestureos_agent/control.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple
import os
import ctypes
from ctypes import wintypes

import pyautogui
from .mathutil import clamp01

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0


# =============================================================================
# FIX: 일부 Python/환경에서 wintypes.ULONG_PTR이 없음
# =============================================================================
if not hasattr(wintypes, "ULONG_PTR"):
    # ULONG_PTR == pointer-sized unsigned integer
    wintypes.ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

# (선택) 혹시 코드 어딘가에서 DWORD_PTR를 쓰면 같이 보강
if not hasattr(wintypes, "DWORD_PTR"):
    wintypes.DWORD_PTR = wintypes.ULONG_PTR


# =============================================================================
# Windows SendInput absolute move (virtual screen) - Paint drag 안정성
# =============================================================================
if os.name == "nt":
    user32 = ctypes.windll.user32

    SM_XVIRTUALSCREEN = 76
    SM_YVIRTUALSCREEN = 77
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79

    INPUT_MOUSE = 0
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_ABSOLUTE = 0x8000
    MOUSEEVENTF_VIRTUALDESK = 0x4000

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", wintypes.ULONG_PTR),
        ]

    class INPUT(ctypes.Structure):
        class _I(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT)]

        _anonymous_ = ("i",)
        _fields_ = [("type", wintypes.DWORD), ("i", _I)]

    # SendInput 시그니처 명시(환경 따라 안정성 향상)
    try:
        user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
        user32.SendInput.restype = wintypes.UINT
    except Exception:
        pass

    def _send_mouse_move_abs_virtual(x: int, y: int):
        """
        Windows 가상 화면(멀티모니터 포함) 기준으로 SendInput 절대좌표 이동.
        - VIRTUALDESK + ABSOLUTE => 0..65535 범위를 가상 데스크탑 전체에 매핑
        """
        # virtual screen metrics
        vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

        # clamp to virtual screen
        vw_ = max(1, int(vw))
        vh_ = max(1, int(vh))
        x = max(int(vx), min(int(vx) + vw_ - 1, int(x)))
        y = max(int(vy), min(int(vy) + vh_ - 1, int(y)))

        # SendInput absolute range 0..65535 over virtual desktop when VIRTUALDESK set
        denom_x = max(1, vw_ - 1)
        denom_y = max(1, vh_ - 1)

        ax = int((x - int(vx)) * 65535 / denom_x)
        ay = int((y - int(vy)) * 65535 / denom_y)

        flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK

        inp = INPUT(type=INPUT_MOUSE)
        inp.mi = MOUSEINPUT(dx=ax, dy=ay, mouseData=0, dwFlags=flags, time=0, dwExtraInfo=0)

        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

else:
    def _send_mouse_move_abs_virtual(x: int, y: int):
        pyautogui.moveTo(x, y)


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

    # (선택) hands_agent에서 set_gain을 찾는 코드가 있으니, 제공해두면 좋음
    def set_gain(self, g: float):
        try:
            self.gain = float(g)
        except Exception:
            pass

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
        # throttle
        if (now_ts - self.last_move_ts) < self.move_interval_sec:
            return
        self.last_move_ts = now_ts

        if os.name == "nt":
            user32 = ctypes.windll.user32
            vx = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
            vy = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
            vw = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
            vh = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN

            x = int(vx + norm_x * max(1, int(vw)))
            y = int(vy + norm_y * max(1, int(vh)))

            # clamp
            x = max(int(vx), min(int(vx) + max(1, int(vw)) - 1, x))
            y = max(int(vy), min(int(vy) + max(1, int(vh)) - 1, y))
        else:
            sx, sy = pyautogui.size()
            x = int(norm_x * sx)
            y = int(norm_y * sy)

        # deadzone
        cur = pyautogui.position()
        if abs(x - cur.x) < self.deadzone_px and abs(y - cur.y) < self.deadzone_px:
            return

        # ✅ Windows: SendInput absolute move (virtual desk)
        try:
            _send_mouse_move_abs_virtual(x, y)
        except Exception:
            # fallback
            try:
                pyautogui.moveTo(x, y)
            except Exception:
                pass
