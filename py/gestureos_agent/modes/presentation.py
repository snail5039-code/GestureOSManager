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
    """PRESENTATION mode (PPT) - 안전/직관 버전 (전역 '양손 브이'와 겹침 방지)

    제스처 기능 요약:
      - (커서 손) OPEN_PALM       : 커서 이동(※ 이동은 hands_agent에서 처리)
      - (커서 손) PINCH_INDEX     : 좌클릭 (복귀/선택)
      - (커서 손) FIST            : 다음 슬라이드 (Right)
      - (커서 손) V_SIGN          : 이전 슬라이드 (Left)
      - (양손) OPEN_PALM+OPEN_PALM : F5 (발표 시작)
      - (양손) FIST+FIST 길게       : ESC (발표 종료)   ※ 오작동 방지
      - (양손) PINCH_INDEX+PINCH_INDEX 길게 : ALT+TAB (직전 앱으로) ※ 링크/영상 갔다가 복귀용
        (전역 '양손 브이' = 모드 메뉴와 겹치지 않게 변경)
    """

    stable_frames: int = 3

    # 길게 유지(hold)로 오작동 방지
    hold_sec: dict = field(default_factory=lambda: {
        "NEXT": 0.08,
        "PREV": 0.08,
        "START": 0.20,
        "END": 0.75,          # ✅ 종료는 길게
        "ACTIVATE": 0.10,     # (옵션) 클릭
        "SWITCH_APP": 0.45,   # ✅ Alt+Tab도 길게(튐 방지)
        # (옵션) 보조 제스처 레이어
        "TAB": 0.10,
        "SHIFT_TAB": 0.10,
        "ENTER": 0.10,
        "PLAY_PAUSE": 0.10,
    })

    # 연타 방지(특히 Alt+Tab은 토글이라 쿨다운 길게)
    cooldown_sec: dict = field(default_factory=lambda: {
        "NEXT": 0.30,
        "PREV": 0.30,
        "START": 0.80,
        "END": 0.90,
        "ACTIVATE": 0.35,
        "SWITCH_APP": 1.20,   # ✅ 왕복 토글 방지
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
            pyautogui.press("right")
        elif token == "PREV":
            pyautogui.press("left")
        elif token == "START":
            pyautogui.press("f5")
        elif token == "END":
            pyautogui.press("esc")
        elif token == "ACTIVATE":
            # ✅ 링크/영상/브라우저 등 “복귀/선택”은 Enter보다 클릭이 확실
            pyautogui.click(button="left")
        elif token == "SWITCH_APP":
            # ✅ 직전 앱 토글(대부분 브라우저↔PPT 복귀용으로 잘 먹힘)
            pyautogui.hotkey("alt", "tab")
        elif token == "TAB":
            pyautogui.press("tab")
        elif token == "SHIFT_TAB":
            pyautogui.hotkey("shift", "tab")
        elif token == "ENTER":
            pyautogui.press("enter")
        elif token == "PLAY_PAUSE":
            # PPT 내 영상/웹 영상 등에서 보통 Space가 토글
            pyautogui.press("space")

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

        # -------------------------
        # 2손 고정 제스처(우선)
        # -------------------------
        if got_cursor and got_other:
            # ✅ ALT+TAB (양손 PINCH)  ← 전역 '양손 브이'와 겹치지 않게 변경
            if cursor_gesture == "PINCH_INDEX" and other_gesture == "PINCH_INDEX":
                token = "SWITCH_APP"
            # ✅ ESC 종료 (양손 FIST 길게)
            elif cursor_gesture == "FIST" and other_gesture == "FIST":
                token = "END"
            # ✅ F5 시작 (양손 OPEN)
            elif cursor_gesture == "OPEN_PALM" and other_gesture == "OPEN_PALM":
                token = "START"

        # -------------------------
        # 보조 레이어(Other-hand hold) → Tab/Shift+Tab/Enter/PlayPause
        # -------------------------
        if token is None and got_cursor and got_other and interact_hold and interact_hold != "NONE":
            if other_gesture == interact_hold:
                token = _pick_token(cursor_gesture, inter, ["TAB", "SHIFT_TAB", "ENTER", "PLAY_PAUSE"])

        # -------------------------
        # 1손 제스처(슬라이드 이동)
        # -------------------------
        if token is None and got_cursor:
            token = _pick_token(cursor_gesture, nav, ["NEXT", "PREV"])

        # (옵션) 클릭 매핑(기본 NONE). PPT 모드 클릭은 hands_agent의 MouseClickDrag가 담당.
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

        # 단발 트리거(연속 클릭/연속 토글 방지)
        self.armed = False


__all__ = ["PresentationHandler"]
