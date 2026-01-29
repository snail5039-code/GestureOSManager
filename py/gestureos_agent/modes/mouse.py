# file: py/gestureos_agent/modes/mouse.py
from __future__ import annotations

"""Mouse mode helpers.

이 프로젝트는 Win11/64bit에서 ctypes SendInput 호출이 미묘하게 깨지면
"커서는 움직이는데 클릭/휠/키는 전부 안 먹는" 증상이 자주 나옵니다.

따라서 마우스 버튼/휠은 로컬 ctypes 재구현 대신,
검증된 공용 유틸(py/gestureos_agent/win_inject.py)만 사용합니다.
"""

from dataclasses import dataclass
import os

from .. import win_inject


INJECT_DEBUG = os.getenv("INJECT_DEBUG", "0").strip() in ("1", "true", "True", "YES", "yes")


def _dlog(*a):
    if INJECT_DEBUG:
        try:
            print("[INJECT][MOUSE]", *a, flush=True)
        except Exception:
            pass


# Keep legacy constants (used by existing state machines)
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800


def _send_mouse(flags: int, data: int = 0) -> bool:
    """Compatibility wrapper for old flag-based calls."""
    ok = False
    try:
        if flags == MOUSEEVENTF_LEFTDOWN:
            ok = win_inject.mouse_left_down()
        elif flags == MOUSEEVENTF_LEFTUP:
            ok = win_inject.mouse_left_up()
        elif flags == MOUSEEVENTF_RIGHTDOWN:
            ok = win_inject.mouse_right_down()
        elif flags == MOUSEEVENTF_RIGHTUP:
            ok = win_inject.mouse_right_up()
        elif flags == MOUSEEVENTF_WHEEL:
            ok = win_inject.mouse_wheel(int(data))
        else:
            ok = False
    except Exception as e:
        _dlog("exception", flags, data, e)
        ok = False

    if INJECT_DEBUG:
        _dlog("send", hex(int(flags)), "data=", int(data), "ok=", ok)
    return bool(ok)


@dataclass
class MouseClickDrag:
    """PINCH_INDEX 같은 제스처를 '왼쪽 버튼 Down/Up'으로 매핑.

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

    # hands_agent 호출 형태에 맞춤:
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

        # right click = down+up
        _send_mouse(MOUSEEVENTF_RIGHTDOWN)
        _send_mouse(MOUSEEVENTF_RIGHTUP)
        self.last_ts = t


@dataclass
class MouseScroll:
    """other hand 홀드(FIST 등) 동안 y 변화량으로 스크롤."""

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
    """MOUSE 모드에서 lock 토글용."""

    hold_sec: float = 0.35
    cooldown_sec: float = 0.8
    _hold_start: float | None = None
    _last_toggle: float = 0.0

    def reset(self):
        self._hold_start = None

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
        if not enabled:
            self.reset()
            return locked

        if not got_cursor:
            self.reset()
            return locked

        g = str(cursor_gesture or "").upper()
        tg = str(toggle_gesture or "").upper()

        if g == tg:
            if self._hold_start is None:
                self._hold_start = t
            if (t - self._hold_start) >= self.hold_sec and t >= (self._last_toggle + self.cooldown_sec):
                locked = not locked
                self._last_toggle = t
                self._hold_start = None
        else:
            self._hold_start = None

        return locked


__all__ = [
    "MouseClickDrag",
    "MouseRightClick",
    "MouseScroll",
    "MouseLockToggle",
]
