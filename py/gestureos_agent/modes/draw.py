from __future__ import annotations

from dataclasses import dataclass
import os
import time
import ctypes
from ctypes import wintypes
import pyautogui

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0


# =============================================================================
# Windows SendInput helpers (Paint drag 안정성)
# =============================================================================
if os.name == "nt":
    user32 = ctypes.windll.user32

    INPUT_MOUSE = 0
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
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

    def _send_mouse(flags: int, dx: int = 0, dy: int = 0, mouseData: int = 0):
        inp = INPUT(type=INPUT_MOUSE)
        inp.mi = MOUSEINPUT(dx=dx, dy=dy, mouseData=mouseData, dwFlags=flags, time=0, dwExtraInfo=0)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

    def _mouse_left_down():
        _send_mouse(MOUSEEVENTF_LEFTDOWN)

    def _mouse_left_up():
        _send_mouse(MOUSEEVENTF_LEFTUP)
else:
    def _mouse_left_down():
        pyautogui.mouseDown()

    def _mouse_left_up():
        pyautogui.mouseUp()


@dataclass
class DrawHandler:
    """
    DRAW 모드:
    - cursor_gesture == PINCH_INDEX 를 "펜다운(드래그)"로 사용
    - Win11 Paint 호환성을 위해 Windows에서는 SendInput으로 down/up
    """
    down_debounce_sec: float = 0.04
    up_debounce_sec: float = 0.02  # ✅ 손 떨림으로 한 프레임 튀는 거 방지용

    sel_hold_sec: float = 0.28
    sel_cooldown_sec: float = 0.60

    pinch_start_ts: float | None = None
    pinch_end_ts: float | None = None
    down: bool = False

    copy_hold: float | None = None
    last_copy_ts: float = 0.0
    copy_fired: bool = False

    cut_hold: float | None = None
    last_cut_ts: float = 0.0
    cut_fired: bool = False

    def reset(self):
        self.pinch_start_ts = None
        self.pinch_end_ts = None

        if self.down:
            try:
                _mouse_left_up()
            except Exception:
                pass
        self.down = False

        self.copy_hold = None
        self.copy_fired = False
        self.cut_hold = None
        self.cut_fired = False

    def update_draw(self, t: float, cursor_gesture: str, can_inject: bool):
        if not can_inject:
            self.reset()
            return

        is_pinch = (cursor_gesture == "PINCH_INDEX")

        # ----------------------------
        # Down debounce
        # ----------------------------
        if is_pinch:
            self.pinch_end_ts = None
            if self.pinch_start_ts is None:
                self.pinch_start_ts = t

            if (not self.down) and ((t - self.pinch_start_ts) >= self.down_debounce_sec):
                try:
                    _mouse_left_down()
                except Exception:
                    # fallback
                    try:
                        pyautogui.mouseDown()
                    except Exception:
                        pass
                self.down = True

        # ----------------------------
        # Up debounce (짧은 튐 방지)
        # ----------------------------
        else:
            self.pinch_start_ts = None

            if self.down:
                if self.pinch_end_ts is None:
                    self.pinch_end_ts = t

                if (t - self.pinch_end_ts) >= self.up_debounce_sec:
                    try:
                        _mouse_left_up()
                    except Exception:
                        try:
                            pyautogui.mouseUp()
                        except Exception:
                            pass
                    self.down = False
                    self.pinch_end_ts = None
            else:
                self.pinch_end_ts = None

    def update_selection_shortcuts(
        self,
        t: float,
        cursor_gesture: str,
        other_gesture: str,
        got_other: bool,
        can_inject: bool,
    ):
        if not can_inject:
            self.copy_hold = None
            self.copy_fired = False
            self.cut_hold = None
            self.cut_fired = False
            return

        mod = got_other and (other_gesture == "PINCH_INDEX")

        # Ctrl+C: mod + cursor V_SIGN hold
        if mod and (cursor_gesture == "V_SIGN"):
            if t < self.last_copy_ts + self.sel_cooldown_sec:
                self.copy_hold = None
                self.copy_fired = False
            else:
                if not self.copy_fired:
                    if self.copy_hold is None:
                        self.copy_hold = t
                    elif (t - self.copy_hold) >= self.sel_hold_sec:
                        pyautogui.hotkey("ctrl", "c")
                        self.last_copy_ts = t
                        self.copy_fired = True
        else:
            self.copy_hold = None
            self.copy_fired = False

        # Ctrl+X: mod + cursor FIST hold
        if mod and (cursor_gesture == "FIST"):
            if t < self.last_cut_ts + self.sel_cooldown_sec:
                self.cut_hold = None
                self.cut_fired = False
            else:
                if not self.cut_fired:
                    if self.cut_hold is None:
                        self.cut_hold = t
                    elif (t - self.cut_hold) >= self.sel_hold_sec:
                        pyautogui.hotkey("ctrl", "x")
                        self.last_cut_ts = t
                        self.cut_fired = True
        else:
            self.cut_hold = None
            self.cut_fired = False
