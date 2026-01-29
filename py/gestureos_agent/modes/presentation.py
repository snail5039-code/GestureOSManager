# py/gestureos_agent/modes/presentation.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

from .. import win_inject


def _pick_token(gesture: str, mapping: Dict[str, str], order: list[str]) -> Optional[str]:
    for tok in order:
        if gesture == mapping.get(tok):
            return tok
    return None


@dataclass
class PresentationHandler:
    """
    PRESENTATION mode (PPT) - Win11 안정 입력 (SendInput 기반)

    제스처 기능 요약:
      - (커서 손) OPEN_PALM       : 커서 이동(※ 이동은 hands_agent에서 처리)
      - (커서 손) PINCH_INDEX     : (옵션) 클릭
      - (커서 손) FIST            : 다음 슬라이드 (Right)
      - (커서 손) V_SIGN          : 이전 슬라이드 (Left)
      - (양손) OPEN_PALM+OPEN_PALM : F5 (발표 시작)
      - (양손) FIST+FIST 길게       : ESC (발표 종료)
      - (양손) PINCH_INDEX+PINCH_INDEX 길게 : ALT+TAB (직전 앱)
    """

    stable_frames: int = 3

    hold_sec: dict = field(default_factory=lambda: {
        "NEXT": 0.08,
        "PREV": 0.08,
        "START": 0.20,
        "END": 0.75,
        "ACTIVATE": 0.10,
        "SWITCH_APP": 0.45,
        "TAB": 0.10,
        "SHIFT_TAB": 0.10,
        "ENTER": 0.10,
        "PLAY_PAUSE": 0.10,
    })

    cooldown_sec: dict = field(default_factory=lambda: {
        "NEXT": 0.30,
        "PREV": 0.30,
        "START": 0.80,
        "END": 0.90,
        "ACTIVATE": 0.35,
        "SWITCH_APP": 1.20,
        "TAB": 0.25,
        "SHIFT_TAB": 0.25,
        "ENTER": 0.25,
        "PLAY_PAUSE": 0.35,
    })

    last_token: str | None = None
    streak: int = 0
    token_start_ts: float = 0.0
    armed: bool = True

    last_fire_map: dict = field(default_factory=lambda: {
        "NEXT": 0.0,
        "PREV": 0.0,
        "START": 0.0,
        "END": 0.0,
        "ACTIVATE": 0.0,
        "SWITCH_APP": 0.0,
        "TAB": 0.0,
        "SHIFT_TAB": 0.0,
        "ENTER": 0.0,
        "PLAY_PAUSE": 0.0,
    })

    # hands_agent 호환용 필드
    mod_until: float = 0.0

    def reset(self):
        self.last_token = None
        self.streak = 0
        self.token_start_ts = 0.0
        self.armed = True
        self.mod_until = 0.0
        for k in list(self.last_fire_map.keys()):
            self.last_fire_map[k] = 0.0

    def _fire(self, token: str):
        if token == "NEXT":
            win_inject.key_press_name("RIGHT")
        elif token == "PREV":
            win_inject.key_press_name("LEFT")
        elif token == "START":
            win_inject.key_press_name("F5")
        elif token == "END":
            win_inject.key_press_name("ESC")
        elif token == "ACTIVATE":
            win_inject.mouse_left_click()
        elif token == "SWITCH_APP":
            win_inject.hotkey("ALT", "TAB")
        elif token == "TAB":
            win_inject.key_press_name("TAB")
        elif token == "SHIFT_TAB":
            win_inject.hotkey("SHIFT", "TAB")
        elif token == "ENTER":
            win_inject.key_press_name("ENTER")
        elif token == "PLAY_PAUSE":
            win_inject.key_press_name("SPACE")

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
        interact_hold = (bindings.get("INTERACT_HOLD") or "NONE")

        # 예전 로직 호환
        if cursor_gesture == "KNIFE":
            cursor_gesture = "OPEN_PALM"
        if other_gesture == "KNIFE":
            other_gesture = "OPEN_PALM"

        token = None

        # 2손 고정 제스처(우선)
        if got_cursor and got_other:
            if cursor_gesture == "PINCH_INDEX" and other_gesture == "PINCH_INDEX":
                token = "SWITCH_APP"
            elif cursor_gesture == "FIST" and other_gesture == "FIST":
                token = "END"
            elif cursor_gesture == "OPEN_PALM" and other_gesture == "OPEN_PALM":
                token = "START"

        # 보조 레이어(Other-hand hold)
        if token is None and got_cursor and got_other and interact_hold and interact_hold != "NONE":
            if other_gesture == interact_hold:
                token = _pick_token(cursor_gesture, inter, ["TAB", "SHIFT_TAB", "ENTER", "PLAY_PAUSE"])

        # 1손 제스처(슬라이드 이동)
        if token is None and got_cursor:
            token = _pick_token(cursor_gesture, nav, ["NEXT", "PREV"])

        # (옵션) 클릭 매핑
        if token is None and got_cursor:
            if cursor_gesture == inter.get("ACTIVATE"):
                token = "ACTIVATE"

        if token is None:
            self.last_token = None
            self.streak = 0
            self.token_start_ts = 0.0
            self.armed = True
            return

        # 안정화(stable_frames)
        if token == self.last_token:
            self.streak += 1
        else:
            self.last_token = token
            self.streak = 1
            self.armed = True
            self.token_start_ts = t

        if self.streak < self.stable_frames:
            return

        need_hold = float(self.hold_sec.get(token, 0.12))
        if (t - self.token_start_ts) < need_hold:
            return

        if not self.armed:
            return

        cd = float(self.cooldown_sec.get(token, 0.30))
        last_fire = float(self.last_fire_map.get(token, 0.0))
        if t < last_fire + cd:
            return

        self._fire(token)
        self.last_fire_map[token] = t
        self.armed = False


__all__ = ["PresentationHandler"]
