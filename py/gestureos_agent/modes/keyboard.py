# file: py/gestureos_agent/modes/keyboard.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

import os
import time
import ctypes
from ctypes import wintypes

# -----------------------------------------------------------------------------
# KEYBOARD MODE (Windows): robust key injection
#
# Why keys were "not working":
# - SendInput was returning ERROR_INVALID_PARAMETER (87) because our ctypes INPUT
#   struct was smaller than Windows' expected INPUT size (we defined only KEYBDINPUT
#   in the union). Windows validates cbSize strictly.
#
# Fix:
# - Define full INPUT union (MOUSEINPUT/KEYBDINPUT/HARDWAREINPUT) to match the
#   real WinAPI struct size.
# - Use WinDLL(use_last_error=True) + ctypes.get_last_error() for debugging.
# - Prefer SCANCODE injection; arrows must include EXTENDED flag.
# -----------------------------------------------------------------------------

KEYBOARD_DEBUG = os.getenv("KEYBOARD_DEBUG", "0").strip() in ("1", "true", "True", "YES", "yes")

def _dlog(*a):
    if KEYBOARD_DEBUG:
        try:
            print("[KB]", *a, flush=True)
        except Exception:
            pass

# Load user32 with last-error support
user32 = ctypes.WinDLL("user32", use_last_error=True)

# Types
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP       = 0x0002
KEYEVENTF_SCANCODE    = 0x0008

MAPVK_VK_TO_VSC = 0

# wintypes.ULONG_PTR isn't always present
try:
    ULONG_PTR = wintypes.ULONG_PTR
except AttributeError:
    ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32

# -----------------------------------------------------------------------------
# WinAPI structs (must match Windows headers)
# -----------------------------------------------------------------------------
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx",          wintypes.LONG),
        ("dy",          wintypes.LONG),
        ("mouseData",   wintypes.DWORD),
        ("dwFlags",     wintypes.DWORD),
        ("time",        wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk",         wintypes.WORD),
        ("wScan",       wintypes.WORD),
        ("dwFlags",     wintypes.DWORD),
        ("time",        wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg",    wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]

class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u",    INPUT_UNION),
    ]

LPINPUT = ctypes.POINTER(INPUT)

# Functions
user32.SendInput.argtypes = (wintypes.UINT, LPINPUT, ctypes.c_int)
user32.SendInput.restype  = wintypes.UINT

user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
user32.MapVirtualKeyW.restype  = wintypes.UINT

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

def _send_inputs(inputs) -> int:
    """Call SendInput and return sent count."""
    sent = int(user32.SendInput(len(inputs), inputs, ctypes.sizeof(INPUT)))
    if sent != len(inputs):
        err = ctypes.get_last_error()
        _dlog(f"SendInput partial/failed sent={sent} need={len(inputs)} last_error={err}")
    return sent

def _send_vk(vk_code: int):
    """Send a key press using a scancode-first strategy (more reliable on Win11)."""
    vk_code = int(vk_code)

    # Extended keys that often need KEYEVENTF_EXTENDEDKEY
    is_extended = vk_code in (0x25, 0x26, 0x27, 0x28)  # LEFT/UP/RIGHT/DOWN

    # 1) Preferred: scancode injection
    scan = int(user32.MapVirtualKeyW(vk_code, MAPVK_VK_TO_VSC)) & 0xFFFF
    if scan:
        flags_down = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if is_extended else 0)
        flags_up   = flags_down | KEYEVENTF_KEYUP

        inp_down = INPUT(type=INPUT_KEYBOARD)
        inp_down.u.ki = KEYBDINPUT(0, scan, flags_down, 0, 0)

        inp_up = INPUT(type=INPUT_KEYBOARD)
        inp_up.u.ki = KEYBDINPUT(0, scan, flags_up, 0, 0)

        arr = (INPUT * 2)(inp_down, inp_up)
        _send_inputs(arr)
        return

    # 2) Fallback: wVk injection
    flags_down = (KEYEVENTF_EXTENDEDKEY if is_extended else 0)
    flags_up   = flags_down | KEYEVENTF_KEYUP

    inp_down = INPUT(type=INPUT_KEYBOARD)
    inp_down.u.ki = KEYBDINPUT(vk_code, 0, flags_down, 0, 0)

    inp_up = INPUT(type=INPUT_KEYBOARD)
    inp_up.u.ki = KEYBDINPUT(vk_code, 0, flags_up, 0, 0)

    arr = (INPUT * 2)(inp_down, inp_up)
    _send_inputs(arr)

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
        _dlog(f"press {token} vk={hex(vk)} extended={vk in (0x25,0x26,0x27,0x28)}")
        try:
            _send_vk(int(vk))
        except Exception as e:
            _dlog("send_vk exception:", repr(e))

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
                token = _pick_token(cursor_gesture, fn_map, ["BACKSPACE", "SPACE", "ENTER", "ESC"])
            if token is None:
                token = _pick_token(cursor_gesture, base_map, ["LEFT", "RIGHT", "UP", "DOWN"])

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
                _dlog("fired token=", token, "cursor=", cursor_gesture, "other=", other_gesture, "mod=", mod_active)
                self._press_token(token)
                self.last_fire_map[token] = t
                self.pressed_once = True
                self.repeat_start_ts = t
                self.last_repeat_ts = t
                return

            if (t - self.repeat_start_ts) < self.repeat_start_sec:
                return
            if t >= self.last_repeat_ts + self.repeat_sec:
                _dlog("repeat token=", token)
                self._press_token(token)
                self.last_fire_map[token] = t
                self.last_repeat_ts = t
            return

        if token in one_shot_tokens:
            if not self.armed:
                return
            _dlog("fired token=", token, "cursor=", cursor_gesture, "other=", other_gesture, "mod=", mod_active)
            self._press_token(token)
            self.last_fire_map[token] = t
            self.armed = False
            return
