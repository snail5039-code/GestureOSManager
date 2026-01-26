# py/gestureos_agent/modes/mouse.py
from __future__ import annotations

from dataclasses import dataclass
import os
import time
import ctypes

try:
    import pyautogui
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0
except Exception:
    pyautogui = None


_IS_WIN = (os.name == "nt")


# -----------------------------------------------------------------------------
# Windows SendInput mouse helpers (클릭/휠)
# -----------------------------------------------------------------------------
if _IS_WIN:
    from ctypes import wintypes

    INPUT_MOUSE = 0
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_WHEEL = 0x0800

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

    def _send_mouse(flags: int, wheel: int = 0):
        user32 = ctypes.windll.user32
        inp = INPUT(type=INPUT_MOUSE, u=INPUT_UNION(mi=MOUSEINPUT(0, 0, wheel, flags, 0, 0)))
        arr = (INPUT * 1)(inp)
        user32.SendInput(1, ctypes.byref(arr), ctypes.sizeof(INPUT))

    def _left_down():
        _send_mouse(MOUSEEVENTF_LEFTDOWN)

    def _left_up():
        _send_mouse(MOUSEEVENTF_LEFTUP)

    def _right_click():
        _send_mouse(MOUSEEVENTF_RIGHTDOWN)
        _send_mouse(MOUSEEVENTF_RIGHTUP)

    def _wheel(delta: int):
        # wheel delta는 120 단위가 기본
        _send_mouse(MOUSEEVENTF_WHEEL, wheel=int(delta))
else:
    def _left_down():
        if pyautogui:
            pyautogui.mouseDown(button="left")

    def _left_up():
        if pyautogui:
            pyautogui.mouseUp(button="left")

    def _right_click():
        if pyautogui:
            pyautogui.click(button="right")

    def _wheel(delta: int):
        if pyautogui:
            pyautogui.scroll(int(delta))


# -----------------------------------------------------------------------------
# MouseClickDrag: pinch로 좌클릭/드래그
# -----------------------------------------------------------------------------
@dataclass
class MouseClickDrag:
    down: bool = False
    dragging: bool = False
    down_ts: float = 0.0
    min_drag_hold: float = 0.10  # pinch를 살짝만 했다가 떼면 그냥 click, 오래면 drag 느낌(실제로는 다운 유지)

    def reset(self):
        if self.down:
            try:
                _left_up()
            except Exception:
                pass
        self.down = False
        self.dragging = False
        self.down_ts = 0.0

    def update(self, t: float, cursor_gesture: str, can_click: bool, click_gesture: str = "PINCH_INDEX"):
        if not can_click:
            # 클릭 금지 상태면 내려가 있던 것도 해제
            if self.down:
                try:
                    _left_up()
                except Exception:
                    pass
            self.down = False
            self.dragging = False
            self.down_ts = 0.0
            return

        g = str(cursor_gesture).upper()
        trig = str(click_gesture).upper()

        is_down = (g == trig)

        if is_down and (not self.down):
            # down edge
            try:
                _left_down()
            except Exception:
                pass
            self.down = True
            self.dragging = False
            self.down_ts = t
            return

        if (not is_down) and self.down:
            # up edge
            try:
                _left_up()
            except Exception:
                pass
            self.down = False
            self.dragging = False
            self.down_ts = 0.0
            return

        if self.down:
            # hold 중이면 dragging 상태만 표시(실제 커서 이동은 hands_agent가 수행)
            if (t - self.down_ts) >= self.min_drag_hold:
                self.dragging = True


# -----------------------------------------------------------------------------
# MouseRightClick: V_SIGN 등으로 우클릭
# -----------------------------------------------------------------------------
@dataclass
class MouseRightClick:
    last_fire_ts: float = 0.0
    cooldown: float = 0.45
    _prev_active: bool = False

    def reset(self):
        self.last_fire_ts = 0.0
        self._prev_active = False

    def update(self, t: float, cursor_gesture: str, can_click: bool, gesture: str = "V_SIGN"):
        if not can_click:
            self._prev_active = False
            return

        g = str(cursor_gesture).upper()
        trig = str(gesture).upper()
        active = (g == trig)

        if active and (not self._prev_active):
            if t >= self.last_fire_ts + self.cooldown:
                try:
                    _right_click()
                except Exception:
                    pass
                self.last_fire_ts = t

        self._prev_active = active


# -----------------------------------------------------------------------------
# MouseScroll: other 손을 FIST 홀드 등으로 스크롤 상태 유지 + y 변화로 휠
# -----------------------------------------------------------------------------
@dataclass
class MouseScroll:
    last_y: float = 0.5
    last_ts: float = 0.0
    accum: float = 0.0
    wheel_step: int = 120
    gain: float = 900.0  # y(0~1) 변화량을 휠로 변환하는 계수
    dead: float = 0.015  # 미세 흔들림 무시

    def reset(self):
        self.last_y = 0.5
        self.last_ts = 0.0
        self.accum = 0.0

    def update(self, t: float, active: bool, other_cy: float, enabled: bool):
        if not enabled or (not active):
            # 비활성화면 상태만 갱신
            self.last_y = float(other_cy)
            self.last_ts = t
            self.accum = 0.0
            return

        y = float(other_cy)
        dy = (y - self.last_y)
        self.last_y = y

        if abs(dy) < self.dead:
            return

        # dy > 0 이면 손이 아래로 -> 보통 아래로 스크롤(휠은 음수/양수 방향이 앱에 따라 다를 수 있음)
        self.accum += dy * self.gain

        # step 이상 쌓이면 휠 발생
        while self.accum >= 1.0:
            try:
                _wheel(-self.wheel_step)
            except Exception:
                pass
            self.accum -= 1.0

        while self.accum <= -1.0:
            try:
                _wheel(self.wheel_step)
            except Exception:
                pass
            self.accum += 1.0


# -----------------------------------------------------------------------------
# MouseLockToggle: MOUSE 모드에서만 잠금 토글 (FIST hold 등)
# -----------------------------------------------------------------------------
@dataclass
class MouseLockToggle:
    hold_sec: float = 0.65
    cooldown_sec: float = 1.0
    _hold_start: float | None = None
    _last_toggle_ts: float = 0.0

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
        if not enabled or (not got_cursor):
            self._hold_start = None
            return locked

        g = str(cursor_gesture).upper()
        trig = str(toggle_gesture).upper()

        if g == trig:
            if self._hold_start is None:
                self._hold_start = t
            if (t - self._hold_start) >= self.hold_sec and (t >= self._last_toggle_ts + self.cooldown_sec):
                self._last_toggle_ts = t
                self._hold_start = None
                return (not locked)
        else:
            self._hold_start = None

        return locked
