# file: py/gestureos_agent/modes/keyboard.py
from __future__ import annotations

"""KEYBOARD mode.

증상(Win11에서 자주 발생):
  - 커서는 움직이는데 키 입력/특수키/방향키가 전혀 안 먹음

원인(대표):
  - SendInput에 전달하는 INPUT struct 크기/union 정의가 Windows 헤더와 다르면
    ERROR_INVALID_PARAMETER(87)로 입력이 전부 무시됨.

해결:
  - 키 주입은 공용 win_inject(정상 크기/스캔코드/EXTENDED 처리 포함)만 사용.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional
import os

from .. import win_inject

try:
    import pyautogui  # non-Windows fallback only

    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0
    pyautogui.MINIMUM_DURATION = 0
    pyautogui.MINIMUM_SLEEP = 0
except Exception:  # pragma: no cover
    pyautogui = None


_IS_WIN = (os.name == "nt")
KEYBOARD_DEBUG = os.getenv("KEYBOARD_DEBUG", "0").strip() in ("1", "true", "True", "YES", "yes")


def _dlog(*a):
    if KEYBOARD_DEBUG:
        try:
            print("[KB]", *a, flush=True)
        except Exception:
            pass


def _press_name(name: str) -> bool:
    name_l = str(name).lower()
    if _IS_WIN:
        ok = win_inject.key_press_name(name_l)
        _dlog("press", name_l, "ok=", ok)
        return bool(ok)
    if pyautogui:
        try:
            pyautogui.press(name_l)
            return True
        except Exception:
            return False
    return False


def _pick_token(gesture: str, mapping: Dict[str, str], order: list[str]) -> Optional[str]:
    g = str(gesture or "").upper()
    for tok in order:
        if g == str(mapping.get(tok, "")).upper():
            return tok
    return None


DEFAULT_BASE: Dict[str, str] = {
    "LEFT": "FIST",
    "RIGHT": "V_SIGN",
    "DOWN": "OPEN_PALM",
    "UP": "PINCH_INDEX",
}

DEFAULT_FN: Dict[str, str] = {
    "BACKSPACE": "FIST",
    "SPACE": "OPEN_PALM",
    "ENTER": "PINCH_INDEX",
    "ESC": "V_SIGN",
}

DEFAULT_FN_HOLD = "PINCH_INDEX"


@dataclass
class KeyboardHandler:
    """Gesture -> keyboard input state machine."""

    stable_frames: int = 3

    # Hold before firing
    hold_sec: dict = field(
        default_factory=lambda: {
            "LEFT": 0.12,
            "RIGHT": 0.12,
            "UP": 0.12,
            "DOWN": 0.12,
            "BACKSPACE": 0.14,
            "SPACE": 0.16,
            "ENTER": 0.16,
            "ESC": 0.18,
        }
    )

    # Cooldown per token
    cooldown_sec: dict = field(
        default_factory=lambda: {
            "LEFT": 0.22,
            "RIGHT": 0.22,
            "UP": 0.22,
            "DOWN": 0.22,
            "BACKSPACE": 0.25,
            "SPACE": 0.35,
            "ENTER": 0.35,
            "ESC": 0.45,
        }
    )

    # Repeat (hold) behaviour
    repeat_start_sec: float = 0.55
    repeat_sec: float = 0.22

    last_token: str | None = None
    streak: int = 0
    token_start_ts: float = 0.0

    pressed_once: bool = False
    repeat_start_ts: float = 0.0
    last_repeat_ts: float = 0.0

    last_fire_map: dict = field(
        default_factory=lambda: {
            "LEFT": 0.0,
            "RIGHT": 0.0,
            "UP": 0.0,
            "DOWN": 0.0,
            "BACKSPACE": 0.0,
            "SPACE": 0.0,
            "ENTER": 0.0,
            "ESC": 0.0,
        }
    )

    def reset(self):
        self.last_token = None
        self.streak = 0
        self.token_start_ts = 0.0
        self.pressed_once = False
        self.repeat_start_ts = 0.0
        self.last_repeat_ts = 0.0

    def _fire(self, token: str) -> bool:
        key_name = token.lower()
        # token names already match win_inject names
        return _press_name(key_name)

    def update(
        self,
        t: float,
        can_inject: bool,
        got_cursor: bool,
        cursor_gesture: str,
        got_other: bool,
        other_gesture: str,
        bindings: dict | None = None,
    ):
        if (not can_inject) or (not got_cursor):
            self.reset()
            return

        bindings = bindings or {}
        base: Dict[str, str] = dict(bindings.get("BASE") or DEFAULT_BASE)
        fn: Dict[str, str] = dict(bindings.get("FN") or DEFAULT_FN)
        fn_hold = str(bindings.get("FN_HOLD") or DEFAULT_FN_HOLD).upper()

        fn_active = bool(got_other and (str(other_gesture).upper() == fn_hold))
        mapping = fn if fn_active else base
        order = ["BACKSPACE", "SPACE", "ENTER", "ESC"] if fn_active else ["LEFT", "RIGHT", "UP", "DOWN"]

        token = _pick_token(cursor_gesture, mapping, order)

        if token is None:
            # clear token tracking but keep cooldown state
            self.last_token = None
            self.streak = 0
            self.token_start_ts = 0.0
            self.pressed_once = False
            return

        # stable frame filter
        if token == self.last_token:
            self.streak += 1
        else:
            self.last_token = token
            self.streak = 1
            self.token_start_ts = t
            self.pressed_once = False
            self.repeat_start_ts = t
            self.last_repeat_ts = 0.0

        if self.streak < int(self.stable_frames):
            return

        # hold time before first fire
        need_hold = float(self.hold_sec.get(token, 0.12))
        if (t - self.token_start_ts) < need_hold:
            return

        # per-token cooldown
        cd = float(self.cooldown_sec.get(token, 0.22))
        last_fire = float(self.last_fire_map.get(token, 0.0))

        # 1) first press
        if not self.pressed_once:
            if t < last_fire + cd:
                return
            if self._fire(token):
                self.last_fire_map[token] = t
            self.pressed_once = True
            self.repeat_start_ts = t
            self.last_repeat_ts = t
            return

        # 2) repeat while holding same gesture
        if (t - self.repeat_start_ts) < float(self.repeat_start_sec):
            return

        # repeat interval (respect cooldown too)
        interval = max(float(self.repeat_sec), cd)
        if t < (self.last_repeat_ts + interval):
            return
        if t < (last_fire + cd):
            return

        if self._fire(token):
            self.last_fire_map[token] = t
        self.last_repeat_ts = t


__all__ = ["KeyboardHandler"]
