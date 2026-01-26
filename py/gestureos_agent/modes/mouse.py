# file: py/gestureos_agent/modes/mouse.py
from __future__ import annotations

from dataclasses import dataclass
import os
import time
import ctypes
from ctypes import wintypes

# -----------------------------------------------------------------------------
# Win11 안정형 마우스 입력: SendInput (+ mouse_event fallback)
# -----------------------------------------------------------------------------

user32 = ctypes.windll.user32

INPUT_MOUSE = 0

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800

WHEEL_DELTA = 120

# ✅ 일부 Python/환경에서 wintypes.ULONG_PTR 없음
try:
    ULONG_PTR = wintypes.ULONG_PTR
except AttributeError:
    ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", INPUT_UNION)]


def _send_mouse(flags: int, data: int = 0) -> bool:
    """SendInput 기반 마우스 이벤트. 실패 시 mouse_event로 fallback."""
    try:
        inp = INPUT(type=INPUT_MOUSE, u=INPUT_UNION(mi=MOUSEINPUT(0, 0, int(data), int(flags), 0, 0)))
        arr = (INPUT * 1)(inp)
        n = user32.SendInput(1, ctypes.byref(arr), ctypes.sizeof(INPUT))
        if n == 1:
            return True
    except Exception:
        pass

    # fallback: mouse_event
    try:
        user32.mouse_event(int(flags), 0, 0, int(data), 0)
        return True
    except Exception:
        return False


@dataclass
class MouseClickDrag:
    """
    PINCH_INDEX 같은 제스처를 "왼쪽 버튼 Down/Up"으로 매핑.
    - pinch 유지: 드래그(Down 유지)
    - pinch 해제: Up
    """
    down: bool = False
    dragging: bool = False
    # 디바운스(짧은 흔들림 방지)
    down_hold_sec: float = 0.02
    up_hold_sec: float = 0.02
    _cand_ts: float = 0.0
    _cand_state: str = ""  # "DOWN" or "UP"

    def reset(self):
        if self.down:
            _send_mouse(MOUSEEVENTF_LEFTUP)
        self.down = False
        self.dragging = False
        self._cand_ts = 0.0
        self._cand_state = ""

    def update(self, t: float, gesture: str, can_inject: bool, click_gesture: str = "PINCH_INDEX"):
        if not can_inject:
            self.reset()
            return

        g = str(gesture or "").upper()
        cg = str(click_gesture or "").upper()

        want_down = (g == cg)

        # --- debounce state machine ---
        if want_down and not self.down:
            if self._cand_state != "DOWN":
                self._cand_state = "DOWN"
                self._cand_ts = t
            if (t - self._cand_ts) >= self.down_hold_sec:
                _send_mouse(MOUSEEVENTF_LEFTDOWN)
                self.down = True
                self.dragging = True
                self._cand_state = ""
                self._cand_ts = 0.0
            return

        if (not want_down) and self.down:
            if self._cand_state != "UP":
                self._cand_state = "UP"
                self._cand_ts = t
            if (t - self._cand_ts) >= self.up_hold_sec:
                _send_mouse(MOUSEEVENTF_LEFTUP)
                self.down = False
                self.dragging = False
                self._cand_state = ""
                self._cand_ts = 0.0
            return

        # stable (no transition)
        self._cand_state = ""
        self._cand_ts = 0.0

@dataclass
class MouseRightClick:
    """우클릭: 트리거 제스처(기본 V_SIGN) 감지 시 Down+Up 1회 발동"""
    cooldown_sec: float = 0.45
    last_ts: float = 0.0

    def reset(self):
        self.last_ts = 0.0

    # ✅ hands_agent 호출 형태에 맞춤:
    # update(t, cursor_gesture, can_inject, gesture=mouse_right_g)
    def update(self, t: float, cursor_gesture: str, can_inject: bool, gesture: str = "V_SIGN"):
        if not can_inject:
            return

        g = str(cursor_gesture or "").upper()
        trig = str(gesture or "").upper()

        if g != trig:
            return
        if t < (self.last_ts + self.cooldown_sec):
            return

        _send_mouse(MOUSEEVENTF_RIGHTDOWN)
        _send_mouse(MOUSEEVENTF_RIGHTUP)
        self.last_ts = t



@dataclass
class MouseScroll:
    """
    other hand 홀드(FIST 등) 동안 y 변화량으로 스크롤.
    hands_agent에서 other_cy(0~1)를 넣어줌.
    """
    speed: float = 1.0
    deadzone: float = 0.02
    last_y: float = 0.5

    def reset(self):
        self.last_y = 0.5

    def update(self, t: float, active: bool, y01: float, can_inject: bool):
        if not can_inject or not active:
            self.last_y = float(y01 if y01 is not None else 0.5)
            return

        y = float(y01 if y01 is not None else 0.5)
        dy = y - self.last_y
        self.last_y = y

        if abs(dy) < self.deadzone:
            return

        # 위로 손이 올라가면( y 감소 ) 휠 업(+)
        wheel = int((-dy) * 1200 * self.speed)
        if wheel == 0:
            wheel = 1 if dy < 0 else -1
        _send_mouse(MOUSEEVENTF_WHEEL, wheel)


@dataclass
class MouseLockToggle:
    """
    MOUSE 모드에서 lock 토글용.
    hands_agent가 locked 상태를 관리하므로 여기서는 단순 토글 신호만 제공.
    """
    hold_sec: float = 0.35
    cooldown_sec: float = 0.8
    _hold_start: float | None = None
    _last_toggle: float = 0.0

    def reset(self):
        self._hold_start = None
        self._last_toggle = 0.0

    def update(
        self,
        t: float,
        cursor_gesture: str,
        cx: float,
        cy: float,
        got_cursor: bool,
        got_other: bool,
        enabled: bool,
        locked: bool,
        toggle_gesture: str = "FIST",
    ) -> bool:
        if not enabled or not got_cursor:
            self._hold_start = None
            return locked

        g = str(cursor_gesture or "").upper()
        tg = str(toggle_gesture or "").upper()

        if g == tg:
            if self._hold_start is None:
                self._hold_start = t
            if (t - self._hold_start) >= self.hold_sec and t >= (self._last_toggle + self.cooldown_sec):
                self._last_toggle = t
                self._hold_start = None
                return (not locked)
        else:
            self._hold_start = None

        return locked
