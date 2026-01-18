# py/gestureos_agent/modes/presentation.py
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
class PresentationHandler:
    """PRESENTATION mode (PPT)

    사용자 설정 바인딩:
      - bindings["NAV"] : {NEXT, PREV}
      - bindings["INTERACT"] : {TAB, SHIFT_TAB, ACTIVATE, PLAY_PAUSE}
      - bindings["INTERACT_HOLD"] : other-hand gate gesture

    고정(2손) 제스처:
      - 양손 OPEN_PALM  : F5
      - 양손 PINCH_INDEX : ESC
    """

    stable_frames: int = 3
    interaction_grace_sec: float = 0.80

    hold_sec: dict = field(default_factory=lambda: {
        "NEXT": 0.08,
        "PREV": 0.08,
        "START": 0.20,
        "END": 0.20,
        "TAB": 0.22,
        "SHIFT_TAB": 0.22,
        "ACTIVATE": 0.10,
        "PLAY_PAUSE": 0.12,
    })

    cooldown_sec: dict = field(default_factory=lambda: {
        "NEXT": 0.30,
        "PREV": 0.30,
        "START": 0.80,
        "END": 0.80,
        "TAB": 0.95,
        "SHIFT_TAB": 0.95,
        "ACTIVATE": 0.40,
        "PLAY_PAUSE": 0.60,
    })

    last_token: str | None = None
    streak: int = 0
    token_start_ts: float = 0.0
    armed: bool = True

    interaction_until: float = 0.0

    last_fire_map: dict = field(default_factory=lambda: {
        "NEXT": 0.0, "PREV": 0.0, "START": 0.0, "END": 0.0,
        "TAB": 0.0, "SHIFT_TAB": 0.0, "ACTIVATE": 0.0, "PLAY_PAUSE": 0.0,
    })

    # hands_agent에서 참고하는 필드(호환용)
    mod_until: float = 0.0

    def reset(self):
        self.last_token = None
        self.streak = 0
        self.token_start_ts = 0.0
        self.armed = True
        self.mod_until = 0.0
        self.interaction_until = 0.0
        for k in list(self.last_fire_map.keys()):
            self.last_fire_map[k] = 0.0

    def _fire(self, token: str):
        if token == "NEXT":
            pyautogui.press("right")
        elif token == "PREV":
            pyautogui.press("left")
        elif token == "START":
            pyautogui.press("f5")
        elif token == "END":
            pyautogui.press("esc")
        elif token == "TAB":
            pyautogui.press("tab")
        elif token == "SHIFT_TAB":
            pyautogui.hotkey("shift", "tab")
        elif token == "ACTIVATE":
            pyautogui.press("enter")
        elif token == "PLAY_PAUSE":
            pyautogui.hotkey("alt", "p")

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
        nav: Dict[str, str] = dict(bindings.get("NAV") or {})
        inter: Dict[str, str] = dict(bindings.get("INTERACT") or {})
        inter_hold: str = str(bindings.get("INTERACT_HOLD") or "FIST").upper()

        # 예전 로직 호환: KNIFE → OPEN_PALM
        if cursor_gesture == "KNIFE":
            cursor_gesture = "OPEN_PALM"
        if other_gesture == "KNIFE":
            other_gesture = "OPEN_PALM"

        token = None

        # 2손 고정(START/END) 우선
        if got_cursor and got_other:
            if cursor_gesture == "PINCH_INDEX" and other_gesture == "PINCH_INDEX":
                token = "END"
            elif cursor_gesture == "OPEN_PALM" and other_gesture == "OPEN_PALM":
                token = "START"

        # 인터랙션 게이트(보조 손)
        if got_other and other_gesture == inter_hold:
            self.interaction_until = t + float(self.interaction_grace_sec or 0.0)
        interaction_mode = (t < self.interaction_until)

        # 1손 토큰 선택
        if token is None and got_cursor:
            if interaction_mode:
                token = _pick_token(cursor_gesture, inter, ["TAB", "SHIFT_TAB", "ACTIVATE", "PLAY_PAUSE"])
            else:
                token = _pick_token(cursor_gesture, nav, ["NEXT", "PREV"])

        if token is None:
            self.last_token = None
            self.streak = 0
            self.token_start_ts = 0.0
            self.armed = True
            return

        # 안정화
        if token == self.last_token:
            self.streak += 1
        else:
            self.last_token = token
            self.streak = 1
            self.armed = True
            self.token_start_ts = t

        if self.streak < self.stable_frames:
            return

        need_hold = self.hold_sec.get(token, 0.12)
        if (t - self.token_start_ts) < need_hold:
            return

        repeatable = token in ("TAB", "SHIFT_TAB")

        if not repeatable and not self.armed:
            return

        cd = self.cooldown_sec.get(token, 0.30)
        last_fire = self.last_fire_map.get(token, 0.0)
        if t < last_fire + cd:
            return

        self._fire(token)
        self.last_fire_map[token] = t

        # repeatable은 계속 허용, 나머지는 단발
        self.armed = True if repeatable else False


__all__ = ["PresentationHandler"]
