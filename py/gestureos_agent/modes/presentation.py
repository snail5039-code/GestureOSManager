# py/gestureos_agent/modes/presentation.py
"""
PRESENTATION mode (PPT) - 안전/직관 버전 (전역 '양손 브이'와 겹침 방지)

제스처 기능 요약(기본값 / 설정으로 일부 변경 가능):
  - (커서 손) OPEN_PALM           : 커서 이동(※ 이동은 hands_agent에서 처리)
  - (커서 손) PINCH_INDEX         : 좌클릭(선택)  (※ 클릭은 hands_agent의 MouseClickDrag로 처리)
  - (커서 손) FIST                : 다음 슬라이드 (Right)
  - (커서 손) V_SIGN              : 이전 슬라이드 (Left)

  - (양손) OPEN_PALM + OPEN_PALM  : F5 (발표 시작)
  - (양손) FIST + FIST (Hold)     : ESC (발표 종료)
  - (양손) PINCH_INDEX + PINCH_INDEX (Hold) : ALT+TAB (직전 앱으로)

NOTE:
- 전역 "양손 V_SIGN"은 모드 메뉴(팔레트)로 쓰므로 여기서는 사용하지 않음.
- 키 주입은 Windows에서는 SendInput(권장), 그 외는 pyautogui fallback.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import pyautogui

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0
pyautogui.MINIMUM_DURATION = 0
pyautogui.MINIMUM_SLEEP = 0

_IS_WIN = (os.name == "nt")
if _IS_WIN:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    # wintypes.ULONG_PTR 없는 파이썬도 있어서 직접 정의
    try:
        ULONG_PTR = wintypes.ULONG_PTR
    except AttributeError:
        ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]

    def _send_vk(vk: int, is_down: bool):
        flags = 0 if is_down else KEYEVENTF_KEYUP
        inp = _INPUT(type=INPUT_KEYBOARD, u=_INPUT_UNION(ki=_KEYBDINPUT(vk, 0, flags, 0, 0)))
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))

    def _tap_vk(vk: int, hold_sec: float = 0.01):
        _send_vk(vk, True)
        time.sleep(max(0.0, hold_sec))
        _send_vk(vk, False)

    def _hotkey_alt_tab():
        VK_MENU = 0x12
        VK_TAB = 0x09
        _send_vk(VK_MENU, True)
        time.sleep(0.02)
        _tap_vk(VK_TAB, hold_sec=0.02)
        time.sleep(0.02)
        _send_vk(VK_MENU, False)


# -----------------------------------------------------------------------------
# config
# -----------------------------------------------------------------------------
NAV_COOLDOWN_SEC = 0.35

START_HOLD_SEC = float(os.getenv("PPT_START_HOLD_SEC", "0.45"))
END_HOLD_SEC = float(os.getenv("PPT_END_HOLD_SEC", "0.55"))
SWITCH_HOLD_SEC = float(os.getenv("PPT_SWITCH_HOLD_SEC", "0.55"))
HOLD_COOLDOWN_SEC = float(os.getenv("PPT_HOLD_COOLDOWN_SEC", "1.0"))


def _get(d: Any, *path: str, default=None):
    cur = d
    for p in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
    return cur if cur is not None else default


@dataclass
class _HoldState:
    start_t: Optional[float] = None
    last_fire_t: float = 0.0

    def reset(self):
        self.start_t = None

    def can_fire(self, t: float, cooldown: float) -> bool:
        return t >= (self.last_fire_t + cooldown)

    def mark_fired(self, t: float):
        self.last_fire_t = t
        self.start_t = None


class PresentationHandler:
    def __init__(self):
        self._nav_last_t = 0.0

        self._hold_start = _HoldState()
        self._hold_end = _HoldState()
        self._hold_switch = _HoldState()

        self._last_tip = ""
        self._other_stable = "NONE"
        self._other_last_change_t = 0.0

        # other-hand gesture flicker 완화
        self._other_stable = "NONE"
        self._other_last_change_t = 0.0

    def reset(self):
        self._nav_last_t = 0.0
        self._hold_start.reset()
        self._hold_end.reset()
        self._hold_switch.reset()
        self._last_tip = ""
        self._other_stable = "NONE"
        self._other_last_change_t = 0.0

    def _emit_tip(self, send_event, text: str):
        # 너무 자주 보내면 UI가 버벅일 수 있어서, 변화가 있을 때만
        if text and text != self._last_tip:
            self._last_tip = text
            if callable(send_event):
                try:
                    send_event("PPT_TIP", {"text": text})
                except Exception:
                    pass

    def _press(self, vk_name: str):
        # Windows: SendInput, else pyautogui fallback
        if _IS_WIN:
            vk = {
                "RIGHT": 0x27,
                "LEFT": 0x25,
                "ESC": 0x1B,
                "F5": 0x74,
            }.get(vk_name)
            if vk is not None:
                try:
                    _tap_vk(vk, hold_sec=0.015)
                    return
                except Exception:
                    pass

        # fallback
        if vk_name == "RIGHT":
            pyautogui.press("right")
        elif vk_name == "LEFT":
            pyautogui.press("left")
        elif vk_name == "ESC":
            pyautogui.press("esc")
        elif vk_name == "F5":
            pyautogui.press("f5")

    def _alt_tab(self):
        if _IS_WIN:
            try:
                _hotkey_alt_tab()
                return
            except Exception:
                pass
        pyautogui.hotkey("alt", "tab")

    def update(
        self,
        t: float,
        can_inject: bool,
        got_cursor: bool,
        cursor_gesture: str,
        got_other: bool,
        other_gesture: str,
        bindings: Optional[Dict[str, Any]] = None,
        send_event=None,
    ) -> Optional[str]:
        """
        returns: optional bubble string (hands_agent가 STATUS cursorBubble로 내보낼 수 있음)
        """

        if not can_inject:
            self.reset()
            return None

        # other-hand gesture가 프레임마다 튀는 경우 hold 제스처가 끊기는 문제 완화
        og = str(other_gesture or "NONE").upper()
        if og != self._other_stable:
            # 짧게 바뀌는 건 무시(기본 120ms)
            if (t - float(self._other_last_change_t)) >= 0.12:
                self._other_stable = og
                self._other_last_change_t = t
        other_gesture = self._other_stable

        # ----------------------------
        # 1) 단일손 NAV (설정값 우선)
        # ----------------------------
        nav = _get(bindings or {}, "NAV", default={})
        next_g = str(_get(nav, "NEXT", default="FIST")).upper()
        prev_g = str(_get(nav, "PREV", default="V_SIGN")).upper()

        if got_cursor and (t >= (self._nav_last_t + NAV_COOLDOWN_SEC)):
            if cursor_gesture == next_g:
                self._press("RIGHT")
                self._nav_last_t = t
                self._emit_tip(send_event, "다음 슬라이드")
                return "PRESENTATION • NEXT"
            if cursor_gesture == prev_g:
                self._press("LEFT")
                self._nav_last_t = t
                self._emit_tip(send_event, "이전 슬라이드")
                return "PRESENTATION • PREV"

        # ----------------------------
        # 2) 양손 고정 제스처 (hold)
        # ----------------------------
        bubble = None
        if got_cursor and got_other:
            # START: OPEN_PALM + OPEN_PALM
            if cursor_gesture == "OPEN_PALM" and other_gesture == "OPEN_PALM":
                if self._hold_start.start_t is None:
                    self._hold_start.start_t = t
                remain = max(0.0, START_HOLD_SEC - (t - self._hold_start.start_t))
                bubble = f"PRESENTATION • START ({remain:.1f}s)"
                if self._hold_start.can_fire(t, HOLD_COOLDOWN_SEC) and (t - self._hold_start.start_t) >= START_HOLD_SEC:
                    self._press("F5")
                    self._hold_start.mark_fired(t)
                    self._emit_tip(send_event, "발표 시작(F5)")
                    return "PRESENTATION • START"
            else:
                self._hold_start.reset()

            # END: FIST + FIST (Hold)
            if cursor_gesture == "FIST" and other_gesture == "FIST":
                if self._hold_end.start_t is None:
                    self._hold_end.start_t = t
                remain = max(0.0, END_HOLD_SEC - (t - self._hold_end.start_t))
                bubble = f"PRESENTATION • END ({remain:.1f}s)"
                if self._hold_end.can_fire(t, HOLD_COOLDOWN_SEC) and (t - self._hold_end.start_t) >= END_HOLD_SEC:
                    self._press("ESC")
                    self._hold_end.mark_fired(t)
                    self._emit_tip(send_event, "발표 종료(ESC)")
                    return "PRESENTATION • END"
            else:
                self._hold_end.reset()

            # SWITCH APP: PINCH + PINCH (Hold)
            if cursor_gesture == "PINCH_INDEX" and other_gesture == "PINCH_INDEX":
                if self._hold_switch.start_t is None:
                    self._hold_switch.start_t = t
                remain = max(0.0, SWITCH_HOLD_SEC - (t - self._hold_switch.start_t))
                bubble = f"PRESENTATION • ALT+TAB ({remain:.1f}s)"
                if self._hold_switch.can_fire(t, HOLD_COOLDOWN_SEC) and (t - self._hold_switch.start_t) >= SWITCH_HOLD_SEC:
                    self._alt_tab()
                    self._hold_switch.mark_fired(t)
                    self._emit_tip(send_event, "직전 앱(ALT+TAB)")
                    return "PRESENTATION • ALT+TAB"
            else:
                self._hold_switch.reset()

        return bubble
