# py/gestureos_agent/modes/draw.py
from __future__ import annotations

from dataclasses import dataclass
import os
import time
import ctypes

import pyautogui

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0
pyautogui.MINIMUM_DURATION = 0
pyautogui.MINIMUM_SLEEP = 0

_IS_WIN = (os.name == "nt")


# =============================================================================
# Win32 SendInput mouse down/up (LEFT) for reliable drawing on Win11
# =============================================================================
if _IS_WIN:
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    try:
        ULONG_PTR = wintypes.ULONG_PTR
    except AttributeError:
        ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32

    INPUT_MOUSE = 0
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004

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

    def _send_left_down():
        mi = _MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0)
        inp = _INPUT(type=INPUT_MOUSE, u=_INPUT_UNION(mi=mi))
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

    def _send_left_up():
        mi = _MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0)
        inp = _INPUT(type=INPUT_MOUSE, u=_INPUT_UNION(mi=mi))
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


@dataclass
class DrawHandler:
    # pinch->down debounce
    down_debounce_sec: float = 0.03

    sel_hold_sec: float = 0.28
    sel_cooldown_sec: float = 0.60

    pinch_start_ts: float | None = None
    down: bool = False

    copy_hold: float | None = None
    last_copy_ts: float = 0.0
    copy_fired: bool = False

    cut_hold: float | None = None
    last_cut_ts: float = 0.0
    cut_fired: bool = False

    def reset(self):
        self.pinch_start_ts = None
        if self.down:
            try:
                if _IS_WIN:
                    _send_left_up()
                else:
                    pyautogui.mouseUp(_pause=False)
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

        if cursor_gesture == "PINCH_INDEX":
            if self.pinch_start_ts is None:
                self.pinch_start_ts = t

            if (not self.down) and ((t - self.pinch_start_ts) >= self.down_debounce_sec):
                try:
                    if _IS_WIN:
                        _send_left_down()
                    else:
                        pyautogui.mouseDown(_pause=False)
                    self.down = True
                except Exception:
                    pass
        else:
            self.pinch_start_ts = None
            if self.down:
                try:
                    if _IS_WIN:
                        _send_left_up()
                    else:
                        pyautogui.mouseUp(_pause=False)
                except Exception:
                    pass
                self.down = False

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
                        try:
                            pyautogui.hotkey("ctrl", "c", _pause=False)
                        except Exception:
                            pass
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
                        try:
                            pyautogui.hotkey("ctrl", "x", _pause=False)
                        except Exception:
                            pass
                        self.last_cut_ts = t
                        self.cut_fired = True
        else:
            self.cut_hold = None
            self.cut_fired = False
