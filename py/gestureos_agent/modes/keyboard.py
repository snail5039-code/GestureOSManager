# file: py/gestureos_agent/modes/keyboard.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

import pyautogui

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0


def _pick_token(gesture: str, mapping: Dict[str, str], order: list[str]) -> Optional[str]:
    for tok in order:
        if gesture == mapping.get(tok):
            return tok
    return None


@dataclass
class KeyboardHandler:
    """KEYBOARD mode 입력(연발 억제 버전)

    기본 정책:
    - 화살표/백스페이스도 기본은 단발 1회만 발동
    - 같은 토큰을 길게 들고 있을 때만 느린 반복 허용
    - SPACE/ENTER/ESC 는 단발(armed + cooldown)

    ✅ 추가: 사용자 설정 바인딩 지원
    - settings.bindings.KEYBOARD.BASE/FN/FN_HOLD 를 통해 제스처를 변경 가능
    """

    stable_frames: int = 3

    # repeat: "길게 들고 있을 때만" 천천히 반복
    repeat_start_sec: float = 0.55
    repeat_sec: float = 0.22

    mod_grace_sec: float = 0.20

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

    last_token: str | None = None
    streak: int = 0
    token_start_ts: float = 0.0

    armed: bool = True

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

    mod_until: float = 0.0

    def reset(self):
        self.last_token = None
        self.streak = 0
        self.token_start_ts = 0.0
        self.armed = True
        self.pressed_once = False
        self.repeat_start_ts = 0.0
        self.last_repeat_ts = 0.0
        self.mod_until = 0.0
        for k in list(self.last_fire_map.keys()):
            self.last_fire_map[k] = 0.0

    def _press_token(self, token: str):
        keymap = {
            "LEFT": "left",
            "RIGHT": "right",
            "UP": "up",
            "DOWN": "down",
            "BACKSPACE": "backspace",
            "SPACE": "space",
            "ENTER": "enter",
            "ESC": "esc",
        }
        k = keymap.get(token)
        if k:
            pyautogui.press(k)

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
        if not can_inject:
            self.reset()
            return

        bindings = bindings or {}
        base_map: Dict[str, str] = dict(bindings.get("BASE") or {})
        fn_map: Dict[str, str] = dict(bindings.get("FN") or {})
        fn_hold: str = str(bindings.get("FN_HOLD") or "PINCH_INDEX").upper()

        # FN(mod) layer: other hand gesture briefly enables
        if got_other and other_gesture == fn_hold:
            self.mod_until = t + self.mod_grace_sec
        mod_active = t < self.mod_until

        token = None

        if got_cursor:
            if mod_active:
                token = _pick_token(
                    cursor_gesture,
                    fn_map,
                    ["BACKSPACE", "SPACE", "ENTER", "ESC"],
                )
            if token is None:
                token = _pick_token(
                    cursor_gesture,
                    base_map,
                    ["LEFT", "RIGHT", "UP", "DOWN"],
                )

        # no token => re-arm and clear repeat state
        if token is None:
            self.last_token = None
            self.streak = 0
            self.token_start_ts = 0.0
            self.armed = True
            self.pressed_once = False
            self.repeat_start_ts = 0.0
            return

        # stability tracking + state reset on token change
        if token == self.last_token:
            self.streak += 1
        else:
            self.last_token = token
            self.streak = 1
            self.armed = True
            self.pressed_once = False
            self.repeat_start_ts = 0.0
            self.token_start_ts = t

        if self.streak < self.stable_frames:
            return

        need_hold = self.hold_sec.get(token, 0.12)
        if (t - self.token_start_ts) < need_hold:
            return

        repeat_tokens = {"LEFT", "RIGHT", "UP", "DOWN", "BACKSPACE"}
        one_shot_tokens = {"SPACE", "ENTER", "ESC"}

        cd = self.cooldown_sec.get(token, 0.25)
        last_fire = self.last_fire_map.get(token, 0.0)
        if t < last_fire + cd:
            return

        # repeatable tokens: first press once, then (if held) slow repeat
        if token in repeat_tokens:
            if not self.pressed_once:
                self._press_token(token)
                self.last_fire_map[token] = t
                self.pressed_once = True
                self.repeat_start_ts = t
                self.last_repeat_ts = t
                return

            # allow repeating only after long hold
            if (t - self.repeat_start_ts) < self.repeat_start_sec:
                return
            if t >= self.last_repeat_ts + self.repeat_sec:
                self._press_token(token)
                self.last_fire_map[token] = t
                self.last_repeat_ts = t
            return

        # one-shot tokens: strict armed gating
        if token in one_shot_tokens:
            if not self.armed:
                return
            self._press_token(token)
            self.last_fire_map[token] = t
            self.armed = False
            return
