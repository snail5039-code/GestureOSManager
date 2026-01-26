# file: py/gestureos_agent/modes/keyboard.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

import time
import ctypes
from ctypes import wintypes

try:
    ULONG_PTR = wintypes.ULONG_PTR
except AttributeError:
    ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32


# -----------------------------------------------------------------------------
# Win11 안정형 키 입력: SendInput
# (주의) 관리자 권한 앱(UAC 상승된 창)에는 일반 권한 프로세스가 키 주입 못함.
# 그 경우 GestureOS Agent를 "관리자 권한으로 실행"해야 함.
# -----------------------------------------------------------------------------

user32 = ctypes.windll.user32

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

# Virtual-Key Codes
VK = {
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "backspace": 0x08,
    "space": 0x20,
    "enter": 0x0D,
    "esc": 0x1B,
}


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", INPUT_UNION)]


def _send_vk(vk_code: int):
    inp_down = INPUT(type=INPUT_KEYBOARD, u=INPUT_UNION(ki=KEYBDINPUT(vk_code, 0, 0, 0, 0)))
    inp_up = INPUT(type=INPUT_KEYBOARD, u=INPUT_UNION(ki=KEYBDINPUT(vk_code, 0, KEYEVENTF_KEYUP, 0, 0)))
    arr = (INPUT * 2)(inp_down, inp_up)
    user32.SendInput(2, ctypes.byref(arr), ctypes.sizeof(INPUT))


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
    """KEYBOARD mode 입력(연발 억제 + 기본 바인딩 내장 + SendInput)"""

    stable_frames: int = 3
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
        if not k:
            return

        vk = VK.get(k)
        if vk is None:
            return

        try:
            _send_vk(int(vk))
        except Exception:
            try:
                time.sleep(0.001)
                _send_vk(int(vk))
            except Exception:
                pass

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

        base_map_in = dict(bindings.get("BASE") or {})
        fn_map_in = dict(bindings.get("FN") or {})
        fn_hold = str(bindings.get("FN_HOLD") or DEFAULT_FN_HOLD).upper()

        base_map: Dict[str, str] = dict(DEFAULT_BASE)
        fn_map: Dict[str, str] = dict(DEFAULT_FN)

        for k, v in base_map_in.items():
            base_map[str(k).upper()] = str(v).upper()
        for k, v in fn_map_in.items():
            fn_map[str(k).upper()] = str(v).upper()

        if got_other and str(other_gesture).upper() == fn_hold:
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

        if token is None:
            self.last_token = None
            self.streak = 0
            self.token_start_ts = 0.0
            self.armed = True
            self.pressed_once = False
            self.repeat_start_ts = 0.0
            return

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

        if token in repeat_tokens:
            if not self.pressed_once:
                self._press_token(token)
                self.last_fire_map[token] = t
                self.pressed_once = True
                self.repeat_start_ts = t
                self.last_repeat_ts = t
                return

            if (t - self.repeat_start_ts) < self.repeat_start_sec:
                return
            if t >= self.last_repeat_ts + self.repeat_sec:
                self._press_token(token)
                self.last_fire_map[token] = t
                self.last_repeat_ts = t
            return

        if token in one_shot_tokens:
            if not self.armed:
                return
            self._press_token(token)
            self.last_fire_map[token] = t
            self.armed = False
            return
