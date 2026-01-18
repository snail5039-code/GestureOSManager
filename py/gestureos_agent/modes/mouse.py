# py/gestureos_agent/modes/mouse.py
from __future__ import annotations

from dataclasses import dataclass
import pyautogui

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0


def _norm_g(v: str | None, default: str) -> str:
    if not v:
        return default
    return str(v).strip().upper()


# ---------------------------------------------------------------------
# Click / Drag (gesture configurable)
# ---------------------------------------------------------------------
@dataclass
class MouseClickDrag:
    pinch_thresh: float = 0.06
    click_tap_max: float = 0.22
    drag_hold_sec: float = 0.28
    click_cooldown: float = 0.30
    doubleclick_gap: float = 0.35

    last_click_ts: float = 0.0
    pinch_start_ts: float | None = None
    dragging: bool = False

    pending_single_click: bool = False
    single_click_deadline: float = 0.0

    def reset(self):
        if self.dragging:
            try:
                pyautogui.mouseUp()
            except Exception:
                pass
        self.dragging = False
        self.pinch_start_ts = None
        self.pending_single_click = False

    def update(
        self,
        t: float,
        cursor_gesture: str,
        can_inject: bool,
        # ✅ 새 방식: click_gesture="PINCH_INDEX" 등
        click_gesture: str | None = None,
        # ✅ 예전 방식 호환: gesture="PINCH_INDEX" 등
        gesture: str | None = None,
        **_kwargs,
    ):
        if not can_inject:
            self.reset()
            return

        cg = _norm_g(cursor_gesture, "NONE")
        pinch_g = _norm_g(click_gesture or gesture, "PINCH_INDEX")

        # delayed single click confirmation
        if self.pending_single_click and t >= self.single_click_deadline:
            if t >= self.last_click_ts + self.click_cooldown:
                pyautogui.click()
                self.last_click_ts = t
            self.pending_single_click = False

        # pinch 유지 중
        if cg == pinch_g:
            if self.pinch_start_ts is None:
                self.pinch_start_ts = t

            if (not self.dragging) and (t - self.pinch_start_ts >= self.drag_hold_sec):
                pyautogui.mouseDown()
                self.dragging = True
            return

        # release 처리
        if self.pinch_start_ts is None:
            return

        dur = t - self.pinch_start_ts

        if self.dragging:
            pyautogui.mouseUp()
            self.dragging = False
        else:
            if dur <= self.click_tap_max:
                if self.pending_single_click:
                    # double click
                    self.pending_single_click = False
                    if t >= self.last_click_ts + self.click_cooldown:
                        pyautogui.doubleClick()
                        self.last_click_ts = t
                else:
                    # single click pending
                    self.pending_single_click = True
                    self.single_click_deadline = t + self.doubleclick_gap

        self.pinch_start_ts = None


# ---------------------------------------------------------------------
# Right Click (gesture configurable)
# ---------------------------------------------------------------------
@dataclass
class MouseRightClick:
    hold_sec: float = 0.35
    cooldown_sec: float = 0.60

    last_fire_ts: float = 0.0
    start_ts: float | None = None

    def reset(self):
        self.start_ts = None

    def update(
        self,
        t: float,
        cursor_gesture: str,
        can_inject: bool,
        # ✅ 새 방식: gesture="V_SIGN" 등
        gesture: str | None = None,
        **_kwargs,
    ):
        if not can_inject:
            self.reset()
            return

        cg = _norm_g(cursor_gesture, "NONE")
        g = _norm_g(gesture, "V_SIGN")

        if cg != g:
            self.start_ts = None
            return

        if t < self.last_fire_ts + self.cooldown_sec:
            self.start_ts = None
            return

        if self.start_ts is None:
            self.start_ts = t
            return

        if (t - self.start_ts) >= self.hold_sec:
            pyautogui.click(button="right")
            self.last_fire_ts = t
            self.start_ts = None


# ---------------------------------------------------------------------
# Scroll (other hand hold gate; unchanged but kwargs-safe)
# ---------------------------------------------------------------------
@dataclass
class MouseScroll:
    gain: int = 1400
    deadzone: float = 0.012
    interval_sec: float = 0.05

    last_scroll_ts: float = 0.0
    anchor_y: float | None = None

    def reset(self):
        self.anchor_y = None

    def update(
        self,
        t: float,
        scroll_active: bool,
        other_cy: float,
        can_inject: bool,
        **_kwargs,
    ):
        if (not can_inject) or (not scroll_active):
            self.anchor_y = None
            return

        if self.anchor_y is None:
            self.anchor_y = other_cy
            return

        if (t - self.last_scroll_ts) < self.interval_sec:
            return

        dy = other_cy - self.anchor_y
        if abs(dy) < self.deadzone:
            return

        amount = int(-dy * self.gain)
        if amount != 0:
            pyautogui.scroll(amount)
            self.last_scroll_ts = t
            self.anchor_y = other_cy


# ---------------------------------------------------------------------
# Lock Toggle (gesture configurable + legacy signature compatible)
# ---------------------------------------------------------------------
@dataclass
class MouseLockToggle:
    hold_sec: float = 2.0
    cooldown_sec: float = 1.0
    center_box: tuple = (0.25, 0.15, 0.75, 0.85)
    still_max_move: float = 0.020

    fist_start: float | None = None
    fist_anchor: tuple | None = None
    last_toggle_ts: float = 0.0

    def reset(self):
        self.fist_start = None
        self.fist_anchor = None

    def update(
        self,
        t: float,
        cursor_gesture: str,
        cx: float | None = None,
        cy: float | None = None,
        got_cursor: bool = True,
        got_other: bool = False,
        enabled: bool = True,
        locked: bool = False,
        # ✅ 새 방식
        toggle_gesture: str | None = None,
        # ✅ 예전 방식(혹시 gesture 이름으로 주는 호출)
        gesture: str | None = None,
        **_kwargs,
    ) -> bool:
        """
        Returns new_locked if toggled, else locked unchanged.
        """
        if not enabled:
            self.reset()
            return locked

        # 두 손이면 잠금 토글 금지(기존 정책 유지)
        if got_other or (not got_cursor):
            self.reset()
            return locked

        if t < self.last_toggle_ts + self.cooldown_sec:
            self.reset()
            return locked

        # cx/cy가 없으면 동작 불가(안전)
        if cx is None or cy is None:
            self.reset()
            return locked

        # center box 안에서만(기존 정책 유지)
        minx, miny, maxx, maxy = self.center_box
        if not (minx <= cx <= maxx and miny <= cy <= maxy):
            self.reset()
            return locked

        cg = _norm_g(cursor_gesture, "NONE")
        g = _norm_g(toggle_gesture or gesture, "FIST")

        if cg != g:
            self.reset()
            return locked

        if self.fist_start is None:
            self.fist_start = t
            self.fist_anchor = (cx, cy)
            return locked

        ax, ay = self.fist_anchor
        if abs(cx - ax) > self.still_max_move or abs(cy - ay) > self.still_max_move:
            # 움직였으면 홀드 다시 시작
            self.fist_start = t
            self.fist_anchor = (cx, cy)
            return locked

        if (t - self.fist_start) >= self.hold_sec:
            self.reset()
            self.last_toggle_ts = t
            return (not locked)

        return locked


__all__ = ["MouseClickDrag", "MouseRightClick", "MouseScroll", "MouseLockToggle"]
