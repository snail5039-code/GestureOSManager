"""
GestureOS Agent (Mouse + Keyboard + RUSH + VKEY/OSK) - SINGLE FILE (agent.py)
"""

import json
import time
import threading
import math
import os
import sys
import subprocess

import cv2
import mediapipe as mp
import pyautogui
from websocket import WebSocketApp


# ============================================================
# CLI FLAGS
# ============================================================
ARGS = set(sys.argv[1:])

HEADLESS = ("--headless" in ARGS)
NO_WS = ("--no-ws" in ARGS)
NO_INJECT = ("--no-inject" in ARGS)

START_ENABLED = ("--start-enabled" in ARGS)
START_VKEY = ("--start-vkey" in ARGS)
START_RUSH = ("--start-rush" in ARGS)
START_KEYBOARD = ("--start-keyboard" in ARGS)

FORCE_CURSOR_LEFT = ("--cursor-left" in ARGS)

# ============================================================
# WebSocket (Spring Boot WS endpoint)
# ============================================================
WS_URL = "ws://127.0.0.1:8080/ws/agent"
_ws = None
_ws_connected = False

# ============================================================
# Preview Window
# ============================================================
PREVIEW = (not HEADLESS)
_window_open = False

# 커서 제어 손(반대로 동작하면 Left로)
CURSOR_HAND_LABEL = "Left" if FORCE_CURSOR_LEFT else "Right"

# ============================================================
# Control box (normalized 0~1)
# - 손 입력 영역(부분 박스)을 화면 전체(0~1)로 맵핑
# ============================================================
CONTROL_BOX = (0.30, 0.35, 0.70, 0.92)
CONTROL_GAIN = 1.35
CONTROL_HALF_W = 0.20
CONTROL_HALF_H = 0.28

# ============================================================
# NEXT_MODE EVENT (both OPEN_PALM hold while locked)
# ============================================================
MODE_HOLD_SEC = 0.8
MODE_COOLDOWN_SEC = 1.2
_last_mode_event_ts = 0.0
_mode_hold_start = None


def send_event(ws, name, payload=None):
    if ws is None or (not _ws_connected):
        return
    msg = {"type": "EVENT", "name": name}
    if payload is not None:
        msg["payload"] = payload
    try:
        ws.send(json.dumps(msg))
    except Exception as e:
        print("[PY] send_event error:", e)


# ============================================================
# (A 방식) Web HUD Mode Menu
# ============================================================
UI_MENU_OPEN_HOLD_SEC = 0.60
UI_MENU_CLOSE_HOLD_SEC = 0.30
UI_MENU_CONFIRM_HOLD_SEC = 0.25
UI_MENU_TIMEOUT_SEC = 5.0
UI_MENU_OPEN_COOLDOWN_SEC = 1.0
UI_MENU_NAV_COOLDOWN_SEC = 0.22

_ui_menu_open_start = None
_ui_menu_close_start = None
_ui_menu_confirm_start = None
_ui_menu_active = False
_ui_menu_until = 0.0
_ui_menu_last_open_ts = 0.0
_ui_menu_last_nav_ts = 0.0
_ui_menu_next_armed = True
_ui_menu_prev_armed = True


# ============================================================
# Motion smoothing / jitter control
# ============================================================
EMA_ALPHA = 0.22
DEADZONE_PX = 3

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

MOVE_INTERVAL_SEC = 1.0 / 60.0
_last_move_ts = 0.0

_ema_x = None
_ema_y = None

# ============================================================
# PINCH / Click / Drag (mouse)
# ============================================================
PINCH_THRESH_INDEX = 0.06

CLICK_TAP_MAX_SEC = 0.22
DRAG_HOLD_SEC = 0.28
CLICK_COOLDOWN_SEC = 0.30

_last_click_ts = 0.0
_pinch_start_ts = None
_dragging = False

DOUBLECLICK_GAP_SEC = 0.35
_pending_single_click = False
_single_click_deadline = 0.0

# ============================================================
# DRAW mode (Paint / Whiteboard)
# - PINCH_INDEX hold => mouseDown (draw)
# - release          => mouseUp
# ============================================================
DRAW_DOWN_DEBOUNCE_SEC = 0.04  # 민감하면 0.06~0.08로 올려도 됨

_draw_pinch_start_ts = None
_draw_down = False


# ============================================================
# DRAW: Selection shortcuts (Paint)
# - other hand PINCH_INDEX acts as modifier
# - (mod) + cursor V_SIGN hold => Ctrl+C (copy)
# - (mod) + cursor FIST  hold => Ctrl+X (cut)
# ============================================================
DRAW_SEL_HOLD_SEC = 0.28
DRAW_SEL_COOLDOWN_SEC = 0.60

_draw_copy_hold = None
_draw_last_copy_ts = 0.0
_draw_copy_fired = False

_draw_cut_hold = None
_draw_last_cut_ts = 0.0
_draw_cut_fired = False


def _draw_reset():
    global _draw_pinch_start_ts, _draw_down
    global _draw_copy_hold, _draw_last_copy_ts, _draw_copy_fired
    global _draw_cut_hold, _draw_last_cut_ts, _draw_cut_fired

    _draw_pinch_start_ts = None
    if _draw_down:
        try:
            pyautogui.mouseUp()
        except Exception:
            pass
    _draw_down = False

    _draw_copy_hold = None
    _draw_last_copy_ts = 0.0
    _draw_copy_fired = False

    _draw_cut_hold = None
    _draw_last_cut_ts = 0.0
    _draw_cut_fired = False


# ============================================================
# PRESENTATION mode (slide control)
# ============================================================
PPT_STABLE_FRAMES = 3
PPT_REPEAT_SEC = 0.18

PPT_HOLD_SEC = {
    "NEXT": 0.10,
    "PREV": 0.10,
    "START": 0.16,
    "START_HERE": 0.16,
    "END": 0.14,
    "BLACK": 0.12,
}

PPT_COOLDOWN_SEC = {
    "START": 0.90,
    "START_HERE": 0.90,
    "END": 0.55,
    "BLACK": 0.40,
}

_ppt_last_token = None
_ppt_streak = 0
_ppt_last_repeat_ts = 0.0
_ppt_last_fire_map = {"START": 0.0, "START_HERE": 0.0, "END": 0.0, "BLACK": 0.0}
_ppt_token_start_ts = 0.0
_ppt_armed = True
_ppt_mod_until = 0.0


def _ppt_reset():
    """PRESENTATION 모드 내부 상태 리셋."""
    global _ppt_last_token, _ppt_streak, _ppt_last_repeat_ts, _ppt_token_start_ts, _ppt_armed, _ppt_last_fire_map
    _ppt_last_token = None
    _ppt_streak = 0
    _ppt_last_repeat_ts = 0.0
    _ppt_token_start_ts = 0.0
    _ppt_armed = True
    if isinstance(_ppt_last_fire_map, dict):
        for k in list(_ppt_last_fire_map.keys()):
            _ppt_last_fire_map[k] = 0.0

def handle_draw_mode(cursor_gesture: str, can_inject: bool):
    """DRAW 모드: PINCH_INDEX 유지하면 좌클릭 드래그로 그리기"""
    global _draw_pinch_start_ts, _draw_down
    t = now()

    if not can_inject:
        _draw_reset()
        return

    if cursor_gesture == "PINCH_INDEX":
        if _draw_pinch_start_ts is None:
            _draw_pinch_start_ts = t
        if (not _draw_down) and ((t - _draw_pinch_start_ts) >= DRAW_DOWN_DEBOUNCE_SEC):
            pyautogui.mouseDown()
            _draw_down = True
    else:
        _draw_pinch_start_ts = None
        if _draw_down:
            pyautogui.mouseUp()
            _draw_down = False


def handle_draw_selection_shortcuts(cursor_gesture: str,
                                   other_gesture: str,
                                   got_other: bool,
                                   can_inject: bool):
    """DRAW 모드: 선택영역 복사/잘라내기 단축키 제스처"""
    global _draw_copy_hold, _draw_last_copy_ts, _draw_copy_fired
    global _draw_cut_hold, _draw_last_cut_ts, _draw_cut_fired

    t = now()

    if not can_inject:
        _draw_copy_hold = None
        _draw_copy_fired = False
        _draw_cut_hold = None
        _draw_cut_fired = False
        return

    # 모디파이어: 보조손 PINCH_INDEX 유지
    mod = got_other and (other_gesture == "PINCH_INDEX")

    # ---- COPY (Ctrl+C): mod + cursor V_SIGN hold
    if mod and (cursor_gesture == "V_SIGN"):
        if t < _draw_last_copy_ts + DRAW_SEL_COOLDOWN_SEC:
            _draw_copy_hold = None
            _draw_copy_fired = False
        else:
            if not _draw_copy_fired:
                if _draw_copy_hold is None:
                    _draw_copy_hold = t
                elif (t - _draw_copy_hold) >= DRAW_SEL_HOLD_SEC:
                    pyautogui.hotkey("ctrl", "c")
                    _draw_last_copy_ts = t
                    _draw_copy_fired = True
    else:
        _draw_copy_hold = None
        _draw_copy_fired = False

    # ---- CUT (Ctrl+X): mod + cursor FIST hold
    if mod and (cursor_gesture == "FIST"):
        if t < _draw_last_cut_ts + DRAW_SEL_COOLDOWN_SEC:
            _draw_cut_hold = None
            _draw_cut_fired = False
        else:
            if not _draw_cut_fired:
                if _draw_cut_hold is None:
                    _draw_cut_hold = t
                elif (t - _draw_cut_hold) >= DRAW_SEL_HOLD_SEC:
                    pyautogui.hotkey("ctrl", "x")
                    _draw_last_cut_ts = t
                    _draw_cut_fired = True
    else:
        _draw_cut_hold = None
        _draw_cut_fired = False


# ============================================================
# Right click (mouse V sign)
# ============================================================
RIGHTCLICK_HOLD_SEC = 0.35
RIGHTCLICK_COOLDOWN_SEC = 0.60
_last_rightclick_ts = 0.0
_vsign_start = None

# ============================================================
# Scroll (mouse, other hand fist + y move)
# ============================================================
SCROLL_GAIN = 1400
SCROLL_DEADZONE = 0.012
SCROLL_INTERVAL_SEC = 0.05
_last_scroll_ts = 0.0
_scroll_anchor_y = None

# ============================================================
# LOCK (mouse only)
# - 커서 손 FIST 2초 고정 => locked 토글
# ============================================================
LOCK_HOLD_SEC = 2.0
LOCK_TOGGLE_COOLDOWN_SEC = 1.0
LOCK_CENTER_BOX = (0.25, 0.15, 0.75, 0.85)
FIST_STILL_MAX_MOVE = 0.020

_fist_start = None
_fist_anchor = None
_last_lock_toggle_ts = 0.0

# ============================================================
# MODE SWITCH by gesture (two-hand combo hold)
# CURSOR = PINCH_INDEX, OTHER = V_SIGN
# ============================================================
MODE_SWITCH_HOLD_SEC = 1.20
MODE_SWITCH_COOLDOWN_SEC = 1.20
MODE_SWITCH_STILL_MAX_MOVE = 0.020
MODE_SWITCH_BOX = LOCK_CENTER_BOX

_ms_start = None
_ms_anchor_cur = None
_ms_anchor_oth = None
_last_mode_switch_ts = 0.0


# ============================================================
# Tracking loss handling
# ============================================================
LOSS_GRACE_SEC = 0.30
HARD_LOSS_SEC = 0.55
REACQUIRE_BLOCK_SEC = 0.12

_last_seen_ts = 0.0
_last_cursor_lm = None
_last_cursor_cxcy = None
_last_cursor_gesture = "NONE"
_reacquire_until = 0.0

# ============================================================
# Runtime state
# ============================================================
enabled = bool(START_ENABLED)
mode = "MOUSE"
if START_KEYBOARD:
    mode = "KEYBOARD"
elif START_RUSH:
    mode = "RUSH"
elif START_VKEY:
    mode = "VKEY"

locked = True
# 기본 안전장치: enabled가 아니라면 잠금 상태로 시작
# --start-enabled 또는 Manager ENABLE 명령을 쓰면 바로 unlock
if enabled:
    locked = False
if mode in ("KEYBOARD", "PRESENTATION", "DRAW", "RUSH", "VKEY"):
    locked = False  # 실사용 편의: 이 모드 진입 시 unlock

# ============================================================
# MediaPipe Hands
# ============================================================
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=2,
    model_complexity=0,  # FPS 우선
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

# ============================================================
# KEYBOARD mode (FN layer)
# ============================================================
KB_STABLE_FRAMES = 3
KB_REPEAT_SEC = 0.12

MOD_GRACE_SEC = 0.20
_mod_until = 0.0

KB_HOLD_SEC = {
    "LEFT": 0.10, "RIGHT": 0.10, "UP": 0.10, "DOWN": 0.10,
    "BACKSPACE": 0.12, "SPACE": 0.16, "ENTER": 0.16, "ESC": 0.18,
}

KB_COOLDOWN_SEC = {
    "SPACE": 0.35,
    "ENTER": 0.35,
    "ESC": 0.45,
}

_kb_last_token = None
_kb_streak = 0
_kb_last_repeat_ts = 0.0
_kb_last_fire_map = {"SPACE": 0.0, "ENTER": 0.0, "ESC": 0.0}
_kb_token_start_ts = 0.0
_kb_armed = True

# ============================================================

# ============================================================
# PRESENTATION mode (PowerPoint / Google Slides)
# - 기본: V_SIGN = Next, FIST = Prev, PINCH_INDEX = Click
# - FN(보조손 PINCH_INDEX 유지) 레이어:
#     V_SIGN = Start(F5), FIST = End(ESC), OPEN_PALM = Black(B), PINCH_INDEX = White(W)
# ============================================================
PPT_STABLE_FRAMES = 3
PPT_REPEAT_SEC = 0.18  # NEXT/PREV 연타 속도

PPT_HOLD_SEC = {
    "NEXT": 0.10,
    "PREV": 0.10,
    "CLICK": 0.10,
    "START": 0.22,
    "END": 0.22,
    "BLACK": 0.18,
    "WHITE": 0.18,
}

PPT_COOLDOWN_SEC = {
    "CLICK": 0.25,
    "START": 0.60,
    "END": 0.60,
    "BLACK": 0.45,
    "WHITE": 0.45,
}

_ppt_last_token = None
_ppt_streak = 0
_ppt_last_repeat_ts = 0.0
_ppt_last_fire_map = {"CLICK": 0.0, "START": 0.0, "END": 0.0, "BLACK": 0.0, "WHITE": 0.0}
_ppt_token_start_ts = 0.0
_ppt_armed = True

# VKEY mode (OSK 클릭 타이핑) - Multi-finger AirTap
# ============================================================
VKEY_TIPS = [8, 12, 16, 20, 4]  # 우선순위: 검지 > 중지 > 약지 > 새끼 > 엄지
VKEY_TIP_TO_PIP = {8: 6, 12: 10, 16: 14, 20: 18, 4: 3}  # 엄지는 IP(3)

AIRTAP_PER_FINGER_COOLDOWN_SEC = 0.18
AIRTAP_GLOBAL_COOLDOWN_SEC = 0.10

AIRTAP_MIN_GAP_SEC = 0.06
AIRTAP_MAX_GAP_SEC = 0.22
AIRTAP_Z_VEL_THRESH = 0.012
AIRTAP_XY_STILL_THRESH = 0.012
AIRTAP_REQUIRE_EXTENDED = True

_air_by_tip = {
    tip: {
        "phase": "IDLE",
        "t0": 0.0,
        "xy0": (0.5, 0.5),
        "fire_xy": None,       # 탭 시작 좌표 고정용
        "last_fire": 0.0,
        "prev_z": None,
        "prev_t": 0.0
    }
    for tip in VKEY_TIPS
}
_vkey_last_global_fire = 0.0

# ===== AirTap event (프론트/Electron 소비용) =====
TAP_SEQ = 0
_last_tap = None  # {"seq":int,"x":float,"y":float,"finger":int,"ts":float}


# ============================================================
# Utility
# ============================================================
def now():
    return time.time()

def clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))

def dist_xy(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])

def palm_center(lm):
    idx = [0, 5, 9, 13, 17]
    xs = [lm[i][0] for i in idx]
    ys = [lm[i][1] for i in idx]
    return (sum(xs) / len(xs), sum(ys) / len(ys))

def map_control_to_screen(cx, cy):
    minx, miny, maxx, maxy = CONTROL_BOX
    ux = (cx - minx) / max(1e-6, (maxx - minx))
    uy = (cy - miny) / max(1e-6, (maxy - miny))
    ux = clamp01(ux)
    uy = clamp01(uy)
    ux = 0.5 + (ux - 0.5) * CONTROL_GAIN
    uy = 0.5 + (uy - 0.5) * CONTROL_GAIN
    return clamp01(ux), clamp01(uy)

def apply_ema(nx, ny):
    global _ema_x, _ema_y
    if _ema_x is None:
        _ema_x, _ema_y = nx, ny
    else:
        _ema_x = EMA_ALPHA * nx + (1.0 - EMA_ALPHA) * _ema_x
        _ema_y = EMA_ALPHA * ny + (1.0 - EMA_ALPHA) * _ema_y
    return _ema_x, _ema_y

def move_cursor(norm_x, norm_y, deadzone_px=DEADZONE_PX):
    global _last_move_ts
    t = now()
    if (t - _last_move_ts) < MOVE_INTERVAL_SEC:
        return
    _last_move_ts = t

    sx, sy = pyautogui.size()
    x = int(norm_x * sx)
    y = int(norm_y * sy)

    cur = pyautogui.position()
    if abs(x - cur.x) < deadzone_px and abs(y - cur.y) < deadzone_px:
        return

    pyautogui.moveTo(x, y)

def finger_extended(lm, tip, pip):
    # tip y가 pip y보다 위면(작으면) 펴짐
    return lm[tip][1] < lm[pip][1]

def open_windows_osk():
    candidates = [
        r"C:\Program Files\Common Files\microsoft shared\ink\TabTip.exe",
        "osk.exe",
    ]
    for cmd in candidates:
        try:
            subprocess.Popen(cmd, shell=True)
            return True
        except Exception:
            pass
    return False


# ============================================================
# Gesture detection
# ============================================================
def is_fist(lm):
    tips = [8, 12, 16, 20]
    pips = [6, 10, 14, 18]
    folded = 0
    for t_, p_ in zip(tips, pips):
        if lm[t_][1] > lm[p_][1]:
            folded += 1
    return folded >= 3

def is_open_palm(lm):
    idx = finger_extended(lm, 8, 6)
    mid = finger_extended(lm, 12, 10)
    ring = finger_extended(lm, 16, 14)
    pinky = finger_extended(lm, 20, 18)
    return idx and mid and ring and pinky

def is_knife_hand(lm):
    if lm is None:
        return False
    if not is_open_palm(lm):
        return False
    d1 = dist_xy(lm[8], lm[12])
    d2 = dist_xy(lm[12], lm[16])
    d3 = dist_xy(lm[16], lm[20])
    avg = (d1 + d2 + d3) / 3.0
    if avg > 0.055:
        return False
    if dist_xy(lm[4], lm[5]) > 0.095:
        return False
    return True

def is_pinch_index(lm):
    return dist_xy(lm[4], lm[8]) < PINCH_THRESH_INDEX

def is_two_finger(lm):
    idx = finger_extended(lm, 8, 6)
    mid = finger_extended(lm, 12, 10)
    ring = finger_extended(lm, 16, 14)
    pinky = finger_extended(lm, 20, 18)
    return idx and mid and (not ring) and (not pinky)

def is_v_sign(lm):
    if not is_two_finger(lm):
        return False
    return dist_xy(lm[8], lm[12]) > 0.06

def classify_gesture(lm):
    if lm is None:
        return "NONE"
    if is_fist(lm):
        return "FIST"
    if is_pinch_index(lm):
        return "PINCH_INDEX"
    if is_v_sign(lm):
        return "V_SIGN"
    if is_knife_hand(lm):
        return "KNIFE"
    if is_open_palm(lm):
        return "OPEN_PALM"
    return "OTHER"


# ============================================================
# (RUSH 안정화) left/right 스왑 방지
# ============================================================
_lr_state = {"left": None, "right": None, "pending_swap": 0}
LR_DEADBAND = 0.06
LR_SWAP_FRAMES = 4
LR_ONEHAND_KEEP_SEC = 0.25
_last_lr_twohand_ts = 0.0

def _pack_from_lm(lm):
    cx, cy = palm_center(lm)
    return {"cx": cx, "cy": cy, "gesture": classify_gesture(lm)}

def _dist2(a, b):
    if a is None or b is None:
        return 1e9
    dx = a["cx"] - b["cx"]
    dy = a["cy"] - b["cy"]
    return dx * dx + dy * dy

def pick_lr_by_screen_x(hands_list):
    global _lr_state, _last_lr_twohand_ts

    if not hands_list:
        _lr_state["left"] = None
        _lr_state["right"] = None
        _lr_state["pending_swap"] = 0
        return None, None

    packs = []
    for label, lm in hands_list:
        if lm is None:
            continue
        packs.append(_pack_from_lm(lm))

    if not packs:
        return None, None

    if len(packs) == 1:
        p = packs[0]
        if now() - _last_lr_twohand_ts < LR_ONEHAND_KEEP_SEC:
            dl = _dist2(p, _lr_state["left"])
            dr = _dist2(p, _lr_state["right"])
            if dl < dr:
                _lr_state["left"] = p
                return _lr_state["left"], _lr_state["right"]
            else:
                _lr_state["right"] = p
                return _lr_state["left"], _lr_state["right"]

        _lr_state["left"] = None
        _lr_state["right"] = p
        _lr_state["pending_swap"] = 0
        return None, p

    packs.sort(key=lambda p: p["cx"])
    left_now = packs[0]
    right_now = packs[-1]
    _last_lr_twohand_ts = now()

    if _lr_state["left"] is None and _lr_state["right"] is None:
        _lr_state["left"] = left_now
        _lr_state["right"] = right_now
        _lr_state["pending_swap"] = 0
        return _lr_state["left"], _lr_state["right"]

    if abs(right_now["cx"] - left_now["cx"]) < LR_DEADBAND:
        cost_keep = _dist2(left_now, _lr_state["left"]) + _dist2(right_now, _lr_state["right"])
        cost_swap = _dist2(left_now, _lr_state["right"]) + _dist2(right_now, _lr_state["left"])
        if cost_swap < cost_keep:
            _lr_state["left"] = right_now
            _lr_state["right"] = left_now
        else:
            _lr_state["left"] = left_now
            _lr_state["right"] = right_now
        _lr_state["pending_swap"] = 0
        return _lr_state["left"], _lr_state["right"]

    cost_keep = _dist2(left_now, _lr_state["left"]) + _dist2(right_now, _lr_state["right"])
    cost_swap = _dist2(left_now, _lr_state["right"]) + _dist2(right_now, _lr_state["left"])
    want_swap = cost_swap + 1e-9 < cost_keep

    if want_swap:
        _lr_state["pending_swap"] += 1
        if _lr_state["pending_swap"] >= LR_SWAP_FRAMES:
            _lr_state["left"] = right_now
            _lr_state["right"] = left_now
            _lr_state["pending_swap"] = 0
    else:
        _lr_state["pending_swap"] = 0
        _lr_state["left"] = left_now
        _lr_state["right"] = right_now

    return _lr_state["left"], _lr_state["right"]

def is_v_sign_switch(lm):
    if not is_two_finger(lm):
        return False
    return dist_xy(lm[8], lm[12]) > 0.045


# ============================================================
# Keyboard helpers
# ============================================================
def _kb_reset():
    global _kb_last_token, _kb_streak, _kb_last_repeat_ts, _kb_token_start_ts, _kb_armed, _mod_until
    _kb_last_token = None
    _kb_streak = 0
    _kb_last_repeat_ts = 0.0
    _kb_token_start_ts = 0.0
    _kb_armed = True
    _mod_until = 0.0
    _kb_last_fire_map["SPACE"] = 0.0
    _kb_last_fire_map["ENTER"] = 0.0
    _kb_last_fire_map["ESC"] = 0.0

def _fire_token(token):
    keymap = {
        "LEFT": "left", "RIGHT": "right", "UP": "up", "DOWN": "down",
        "BACKSPACE": "backspace", "SPACE": "space", "ENTER": "enter", "ESC": "esc",
    }
    k = keymap.get(token)
    if k:
        pyautogui.press(k)


# ============================================================
# Mode apply (WS/gesture 공통)
# ============================================================
def apply_set_mode(new_mode: str):
    """
    모드 전환을 한 곳에서 처리.
    - WS 명령(SET_MODE)과 로컬 키 입력 모두 이 함수를 사용.
    """
    global mode, locked
    global _dragging, _pinch_start_ts, _pending_single_click
    global _ema_x, _ema_y

    nm = str(new_mode).upper()
    if nm == "PPT":
        nm = "PRESENTATION"
    if nm == "PAINT":
        nm = "DRAW"

    allowed = {"MOUSE", "KEYBOARD", "PRESENTATION", "DRAW", "RUSH", "VKEY"}
    if nm not in allowed:
        print("[PY] apply_set_mode ignored:", new_mode)
        return

    # 공통: 커서 EMA 초기화
    _ema_x = None
    _ema_y = None

    # leaving DRAW: draw drag 해제
    if str(mode).upper() == "DRAW" and nm != "DRAW":
        _draw_reset()

    # leaving MOUSE: 드래그/클릭 상태 해제
    if nm != "MOUSE":
        if _dragging:
            try:
                pyautogui.mouseUp()
            except Exception:
                pass
        _dragging = False
        _pinch_start_ts = None
        _pending_single_click = False

    # entering: 모드별 기본 잠금 정책
    if nm in ("KEYBOARD", "PRESENTATION", "DRAW", "RUSH", "VKEY"):
        locked = False

    # 모드별 상태 리셋
    _kb_reset()
    _ppt_reset()
    _draw_reset()
    _reset_vkey_states()

    if nm == "VKEY":
        open_windows_osk()

    mode = nm
    print("[PY] apply_set_mode ->", mode)

def ws_send_set_mode(new_mode: str, source="GESTURE"):
    global _ws
    if _ws is None or (not _ws_connected):
        return
    try:
        m = str(new_mode).upper()
        if m == "PPT":
            m = "PRESENTATION"
        if m == "PAINT":
            m = "DRAW"
        _ws.send(json.dumps({"type": "SET_MODE", "mode": m, "source": source}))
    except Exception as e:
        print("[PY] ws_send_set_mode error:", e)


# ============================================================
# (A 방식) Web HUD Mode Menu handler
# ============================================================
def handle_ui_mode_menu(cursor_gesture: str, other_gesture: str, got_other_hand: bool) -> bool:
    global _ui_menu_open_start, _ui_menu_close_start, _ui_menu_confirm_start
    global _ui_menu_active, _ui_menu_until, _ui_menu_last_open_ts, _ui_menu_last_nav_ts
    global _ui_menu_next_armed, _ui_menu_prev_armed

    t = now()

    # enabled 꺼지면 강제 종료
    if not enabled:
        if _ui_menu_active:
            _ui_menu_active = False
            send_event(_ws, "MODE_MENU_CLOSE")
        _ui_menu_open_start = None
        _ui_menu_close_start = None
        _ui_menu_confirm_start = None
        return False

    # -------- 메뉴 닫힘 상태: 열기 감지 --------
    if not _ui_menu_active:
        both_fist = got_other_hand and (cursor_gesture == "FIST") and (other_gesture == "FIST")
        if both_fist:
            if _ui_menu_open_start is None:
                _ui_menu_open_start = t
            if (t - _ui_menu_open_start) >= UI_MENU_OPEN_HOLD_SEC and t >= (_ui_menu_last_open_ts + UI_MENU_OPEN_COOLDOWN_SEC):
                _ui_menu_active = True
                _ui_menu_until = t + UI_MENU_TIMEOUT_SEC
                _ui_menu_last_open_ts = t
                _ui_menu_open_start = None
                _ui_menu_close_start = None
                _ui_menu_confirm_start = None
                _ui_menu_last_nav_ts = 0.0
                _ui_menu_next_armed = True
                _ui_menu_prev_armed = True
                send_event(_ws, "OPEN_MODE_MENU", {"mode": str(mode).upper()})
                return True
        else:
            _ui_menu_open_start = None
        return False

    # -------- 메뉴 열린 상태 --------
    if t >= _ui_menu_until:
        _ui_menu_active = False
        send_event(_ws, "MODE_MENU_CLOSE")
        _ui_menu_close_start = None
        _ui_menu_confirm_start = None
        return False

    consume = True

    # CLOSE: both FIST hold
    both_fist = got_other_hand and (cursor_gesture == "FIST") and (other_gesture == "FIST")
    if both_fist:
        if _ui_menu_close_start is None:
            _ui_menu_close_start = t
        if (t - _ui_menu_close_start) >= UI_MENU_CLOSE_HOLD_SEC:
            _ui_menu_active = False
            send_event(_ws, "MODE_MENU_CLOSE")
            _ui_menu_close_start = None
            _ui_menu_confirm_start = None
            return True
    else:
        _ui_menu_close_start = None

    # CONFIRM: both OPEN_PALM hold
    both_open = got_other_hand and (cursor_gesture == "OPEN_PALM") and (other_gesture == "OPEN_PALM")
    if both_open:
        if _ui_menu_confirm_start is None:
            _ui_menu_confirm_start = t
        if (t - _ui_menu_confirm_start) >= UI_MENU_CONFIRM_HOLD_SEC:
            _ui_menu_active = False
            send_event(_ws, "MODE_MENU_CONFIRM")
            _ui_menu_confirm_start = None
            _ui_menu_close_start = None
            return True
    else:
        _ui_menu_confirm_start = None

    # NAV: PINCH_INDEX -> NEXT, V_SIGN -> PREV (edge + cooldown)
    if cursor_gesture != "PINCH_INDEX":
        _ui_menu_next_armed = True
    if cursor_gesture != "V_SIGN":
        _ui_menu_prev_armed = True

    if cursor_gesture == "PINCH_INDEX" and _ui_menu_next_armed and t >= (_ui_menu_last_nav_ts + UI_MENU_NAV_COOLDOWN_SEC):
        send_event(_ws, "MODE_MENU_NEXT")
        _ui_menu_last_nav_ts = t
        _ui_menu_next_armed = False
        _ui_menu_until = t + UI_MENU_TIMEOUT_SEC
        return True

    if cursor_gesture == "V_SIGN" and _ui_menu_prev_armed and t >= (_ui_menu_last_nav_ts + UI_MENU_NAV_COOLDOWN_SEC):
        send_event(_ws, "MODE_MENU_PREV")
        _ui_menu_last_nav_ts = t
        _ui_menu_prev_armed = False
        _ui_menu_until = t + UI_MENU_TIMEOUT_SEC
        return True

    return consume


# ============================================================
# LOCK handler (mouse only)
# ============================================================
def handle_lock(cursor_gesture, cx, cy, got_cursor_hand, got_other_hand, mode_switch_block):
    global locked, _fist_start, _fist_anchor, _last_lock_toggle_ts, _reacquire_until
    t = now()

    if not enabled:
        _fist_start = None
        _fist_anchor = None
        return

    # 두손 잡히면 lock 금지
    if got_other_hand:
        _fist_start = None
        _fist_anchor = None
        return

    # 모드전환 홀드 중 lock 금지
    if mode_switch_block:
        _fist_start = None
        _fist_anchor = None
        return

    if not got_cursor_hand:
        _fist_start = None
        _fist_anchor = None
        return

    if t < _last_lock_toggle_ts + LOCK_TOGGLE_COOLDOWN_SEC:
        _fist_start = None
        _fist_anchor = None
        return

    minx, miny, maxx, maxy = LOCK_CENTER_BOX
    if not (minx <= cx <= maxx and miny <= cy <= maxy):
        _fist_start = None
        _fist_anchor = None
        return

    if cursor_gesture != "FIST":
        _fist_start = None
        _fist_anchor = None
        return

    if _fist_start is None:
        _fist_start = t
        _fist_anchor = (cx, cy)
        return

    ax, ay = _fist_anchor
    if abs(cx - ax) > FIST_STILL_MAX_MOVE or abs(cy - ay) > FIST_STILL_MAX_MOVE:
        _fist_start = t
        _fist_anchor = (cx, cy)
        return

    if (t - _fist_start) >= LOCK_HOLD_SEC:
        locked = not locked
        _fist_start = None
        _fist_anchor = None
        _last_lock_toggle_ts = t
        _reacquire_until = t + 0.20


# ============================================================
# Mouse: Click / Drag
# ============================================================
def handle_index_pinch_click_drag(cursor_gesture, can_inject):
    global _pinch_start_ts, _dragging, _last_click_ts
    global _pending_single_click, _single_click_deadline

    t = now()

    if not can_inject:
        if _dragging:
            try:
                pyautogui.mouseUp()
            except Exception:
                pass
            _dragging = False
        _pinch_start_ts = None
        _pending_single_click = False
        return

    # 싱글클릭 지연 확정
    if _pending_single_click and t >= _single_click_deadline:
        if t >= _last_click_ts + CLICK_COOLDOWN_SEC:
            pyautogui.click()
            _last_click_ts = t
        _pending_single_click = False

    if cursor_gesture == "PINCH_INDEX":
        if _pinch_start_ts is None:
            _pinch_start_ts = t

        if (not _dragging) and (t - _pinch_start_ts >= DRAG_HOLD_SEC):
            pyautogui.mouseDown()
            _dragging = True
    else:
        if _pinch_start_ts is not None:
            dur = t - _pinch_start_ts

            if _dragging:
                pyautogui.mouseUp()
                _dragging = False
            else:
                if dur <= CLICK_TAP_MAX_SEC:
                    if _pending_single_click:
                        _pending_single_click = False
                        if t >= _last_click_ts + CLICK_COOLDOWN_SEC:
                            pyautogui.doubleClick()
                            _last_click_ts = t
                    else:
                        _pending_single_click = True
                        _single_click_deadline = t + DOUBLECLICK_GAP_SEC

        _pinch_start_ts = None


# ============================================================
# Mouse: Right click
# ============================================================
def handle_right_click(cursor_gesture, can_inject):
    global _vsign_start, _last_rightclick_ts
    t = now()

    if not can_inject:
        _vsign_start = None
        return

    if cursor_gesture != "V_SIGN":
        _vsign_start = None
        return

    if t < _last_rightclick_ts + RIGHTCLICK_COOLDOWN_SEC:
        _vsign_start = None
        return

    if _vsign_start is None:
        _vsign_start = t
        return

    if (t - _vsign_start) >= RIGHTCLICK_HOLD_SEC:
        pyautogui.click(button="right")
        _last_rightclick_ts = t
        _vsign_start = None


# ============================================================
# Mouse: Scroll
# ============================================================
def handle_scroll_other_hand(scroll_active, scroll_cy, can_inject):
    global _scroll_anchor_y, _last_scroll_ts
    t = now()

    if (not can_inject) or (not scroll_active):
        _scroll_anchor_y = None
        return

    if _scroll_anchor_y is None:
        _scroll_anchor_y = scroll_cy
        return

    if (t - _last_scroll_ts) < SCROLL_INTERVAL_SEC:
        return

    dy = scroll_cy - _scroll_anchor_y
    if abs(dy) < SCROLL_DEADZONE:
        return

    amount = int(-dy * SCROLL_GAIN)
    if amount != 0:
        pyautogui.scroll(amount)
        _last_scroll_ts = t
        _scroll_anchor_y = scroll_cy



# ============================================================
# Keyboard mode
# ============================================================
def handle_keyboard_mode(can_inject,
                         got_cursor, cursor_gesture,
                         got_other, other_gesture):
    global _kb_last_token, _kb_streak, _kb_last_repeat_ts, _kb_token_start_ts, _kb_armed
    global _mod_until

    t = now()

    if not can_inject:
        _kb_reset()
        return

    if got_other and other_gesture == "PINCH_INDEX":
        _mod_until = t + MOD_GRACE_SEC
    mod_active = (t < _mod_until)

    token = None

    # FN layer
    if mod_active and got_cursor:
        if cursor_gesture == "FIST":
            token = "BACKSPACE"
        elif cursor_gesture == "OPEN_PALM":
            token = "SPACE"
        elif cursor_gesture == "PINCH_INDEX":
            token = "ENTER"
        elif cursor_gesture == "V_SIGN":
            token = "ESC"

    # base layer
    if token is None and got_cursor:
        if cursor_gesture == "FIST":
            token = "LEFT"
        elif cursor_gesture == "V_SIGN":
            token = "RIGHT"
        elif cursor_gesture == "PINCH_INDEX":
            token = "UP"
        elif cursor_gesture == "OPEN_PALM":
            token = "DOWN"

    if token is None:
        _kb_last_token = None
        _kb_streak = 0
        _kb_token_start_ts = 0.0
        _kb_armed = True
        return

    if token == _kb_last_token:
        _kb_streak += 1
    else:
        _kb_last_token = token
        _kb_streak = 1
        _kb_armed = True
        _kb_token_start_ts = t

    if _kb_streak < KB_STABLE_FRAMES:
        return

    need_hold = KB_HOLD_SEC.get(token, 0.12)
    if (t - _kb_token_start_ts) < need_hold:
        return

    repeat_tokens = {"LEFT", "RIGHT", "UP", "DOWN", "BACKSPACE"}
    one_shot_tokens = {"SPACE", "ENTER", "ESC"}

    if token in repeat_tokens:
        if t >= _kb_last_repeat_ts + KB_REPEAT_SEC:
            _fire_token(token)
            _kb_last_repeat_ts = t
        return

    if token in one_shot_tokens:
        if not _kb_armed:
            return

        cd = KB_COOLDOWN_SEC.get(token, 0.30)
        last_fire = _kb_last_fire_map.get(token, 0.0)
        if t < last_fire + cd:
            return

        _fire_token(token)
        _kb_last_fire_map[token] = t
        _kb_armed = False
        return


# ============================================================
# VKEY: Multi-finger AirTap
# ============================================================

# ============================================================
# PRESENTATION mode
# ============================================================
def _ppt_fire_token(token: str):
    if token == "NEXT":
        pyautogui.press("right")
    elif token == "PREV":
        pyautogui.press("left")
    elif token == "CLICK":
        pyautogui.click()
    elif token == "START":
        pyautogui.press("f5")
    elif token == "END":
        pyautogui.press("esc")
    elif token == "BLACK":
        pyautogui.press("b")
    elif token == "WHITE":
        pyautogui.press("w")

def handle_presentation_mode(can_inject,
                             got_cursor, cursor_gesture,
                             got_other, other_gesture):
    """
    PRESENTATION:
    - V_SIGN  : Next (Right Arrow)
    - FIST    : Prev (Left Arrow)
    - PINCH   : Click (Laser/Hyperlink 등)
    - FN(보조손 PINCH_INDEX 유지):
        V_SIGN    : Start show (F5)
        FIST      : End show (ESC)
        OPEN_PALM : Black screen (B)
        PINCH     : White screen (W)
    """
    global _ppt_last_token, _ppt_streak, _ppt_last_repeat_ts, _ppt_token_start_ts, _ppt_armed
    global _mod_until

    t = now()

    if not can_inject:
        _ppt_reset()
        return

    # modifier: other hand PINCH_INDEX 유지
    if got_other and other_gesture == "PINCH_INDEX":
        _mod_until = t + MOD_GRACE_SEC
    mod_active = (t < _mod_until)

    token = None

    if got_cursor:
        if mod_active:
            if cursor_gesture == "V_SIGN":
                token = "START"
            elif cursor_gesture == "FIST":
                token = "END"
            elif cursor_gesture == "OPEN_PALM":
                token = "BLACK"
            elif cursor_gesture == "PINCH_INDEX":
                token = "WHITE"
        else:
            if cursor_gesture == "V_SIGN":
                token = "NEXT"
            elif cursor_gesture == "FIST":
                token = "PREV"
            elif cursor_gesture == "PINCH_INDEX":
                token = "CLICK"

    if token is None:
        _ppt_last_token = None
        _ppt_streak = 0
        _ppt_token_start_ts = 0.0
        _ppt_armed = True
        return

    if token == _ppt_last_token:
        _ppt_streak += 1
    else:
        _ppt_last_token = token
        _ppt_streak = 1
        _ppt_armed = True
        _ppt_token_start_ts = t

    if _ppt_streak < PPT_STABLE_FRAMES:
        return

    need_hold = PPT_HOLD_SEC.get(token, 0.15)
    if (t - _ppt_token_start_ts) < need_hold:
        return

    repeat_tokens = {"NEXT", "PREV"}
    one_shot_tokens = {"CLICK", "START", "END", "BLACK", "WHITE"}

    if token in repeat_tokens:
        if t >= _ppt_last_repeat_ts + PPT_REPEAT_SEC:
            _ppt_fire_token(token)
            _ppt_last_repeat_ts = t
        return

    if token in one_shot_tokens:
        if not _ppt_armed:
            return

        cd = PPT_COOLDOWN_SEC.get(token, 0.35)
        last_fire = _ppt_last_fire_map.get(token, 0.0)
        if t < last_fire + cd:
            return

        _ppt_fire_token(token)
        _ppt_last_fire_map[token] = t
        _ppt_armed = False
        return

def _hand_scale(lm):
    return max(1e-6, dist_xy(lm[0], lm[9]))

def _is_tip_extended(lm, tip):
    pip = VKEY_TIP_TO_PIP.get(tip)
    if pip is None:
        return True

    if tip in (8, 12, 16, 20):
        return finger_extended(lm, tip, pip)

    # 엄지는 y 비교가 약해서 거리 기반 (오탭 감소 목적)
    return dist_xy(lm[tip], lm[pip]) > 0.020

def _airtap_fired_for_tip(lm, tip):
    st = _air_by_tip[tip]
    t = now()

    if lm is None:
        st["phase"] = "IDLE"
        st["prev_z"] = None
        return False

    if AIRTAP_REQUIRE_EXTENDED and (not _is_tip_extended(lm, tip)):
        st["phase"] = "IDLE"
        return False

    if t < st["last_fire"] + AIRTAP_PER_FINGER_COOLDOWN_SEC:
        return False

    s = _hand_scale(lm)

    # z 정규화: wrist(0) 대비 tip
    z = (lm[tip][2] - lm[0][2]) / s
    xy = (lm[tip][0], lm[tip][1])

    if st["prev_z"] is None:
        st["prev_z"] = z
        st["prev_t"] = t
        return False

    dt = max(1e-6, t - st["prev_t"])
    dz = (z - st["prev_z"]) / dt
    st["prev_z"] = z
    st["prev_t"] = t

    # MediaPipe z: 카메라에 가까워질수록 더 "음수"인 경우가 많음
    if st["phase"] == "IDLE":
        if dz < -AIRTAP_Z_VEL_THRESH:
            st["phase"] = "DOWNING"
            st["t0"] = t
            st["xy0"] = xy
            st["fire_xy"] = None
        return False

    if st["phase"] == "DOWNING":
        # 탭 중 XY 많이 움직이면 취소
        if dist_xy(xy, st["xy0"]) > AIRTAP_XY_STILL_THRESH:
            st["phase"] = "IDLE"
            return False

        # 너무 길면 취소
        if (t - st["t0"]) > AIRTAP_MAX_GAP_SEC:
            st["phase"] = "IDLE"
            return False

        # 복귀: dz가 큰 양수
        if dz > AIRTAP_Z_VEL_THRESH:
            gap = t - st["t0"]
            st["phase"] = "IDLE"
            if AIRTAP_MIN_GAP_SEC <= gap <= AIRTAP_MAX_GAP_SEC:
                st["last_fire"] = t
                st["fire_xy"] = st["xy0"]   # ✅ 탭 시작 좌표 고정
                return True
        return False

    st["phase"] = "IDLE"
    return False

def _reset_vkey_states():
    global _vkey_last_global_fire, TAP_SEQ, _last_tap
    _vkey_last_global_fire = 0.0
    TAP_SEQ = 0
    _last_tap = None
    for tip in VKEY_TIPS:
        st = _air_by_tip[tip]
        st["phase"] = "IDLE"
        st["t0"] = 0.0
        st["xy0"] = (0.5, 0.5)
        st["fire_xy"] = None
        st["last_fire"] = 0.0
        st["prev_z"] = None
        st["prev_t"] = 0.0

def handle_vkey_mode(can_inject, cursor_lm):
    """
    VKEY(OSK)
    - AirTap 감지 시 tap 이벤트 생성 (tapSeq/tapX/tapY/tapFinger)
    - 기본: Python이 OS 클릭도 수행 (NO_INJECT면 클릭 안 함)
    """
    global _vkey_last_global_fire, TAP_SEQ, _last_tap

    if (not can_inject) or cursor_lm is None:
        for tip in VKEY_TIPS:
            _air_by_tip[tip]["phase"] = "IDLE"
        return

    t = now()

    if t < _vkey_last_global_fire + AIRTAP_GLOBAL_COOLDOWN_SEC:
        return

    fired_tip = None
    for tip in VKEY_TIPS:
        if _airtap_fired_for_tip(cursor_lm, tip):
            fired_tip = tip
            break

    if fired_tip is None:
        return

    st = _air_by_tip[fired_tip]
    if st.get("fire_xy") is not None:
        px, py = st["fire_xy"]
    else:
        px, py = cursor_lm[fired_tip][0], cursor_lm[fired_tip][1]

    ux, uy = map_control_to_screen(px, py)

    TAP_SEQ += 1
    _last_tap = {"seq": TAP_SEQ, "x": float(ux), "y": float(uy), "finger": int(fired_tip), "ts": float(t)}

    # 실제 OS 클릭 (NO_INJECT면 수행 안 함)
    if not NO_INJECT:
        sx, sy = pyautogui.size()
        x = int(ux * sx)
        y = int(uy * sy)
        try:
            pyautogui.click(x=x, y=y)
        except Exception:
            pass

    _vkey_last_global_fire = t


# ============================================================
# WS callbacks
# ============================================================
def _lm_to_payload(lm):
    if lm is None:
        return []
    return [{"x": float(p[0]), "y": float(p[1]), "z": float(p[2])} for p in lm]

def send_status(
    ws,
    fps,
    cursor_gesture,
    can_mouse_inject,
    can_keyboard_inject,
    scroll_active,
    other_gesture,
    rush_left=None,
    rush_right=None,
    cursor_lm=None,
    other_lm=None,
):
    if NO_WS:
        return
    if ws is None or (not _ws_connected):
        return

    mode_u = str(mode).upper()

    payload = {
        "type": "STATUS",
        "enabled": bool(enabled),
        "mode": str(mode),
        "locked": bool(locked),
        "preview": bool(PREVIEW),

        "gesture": str(cursor_gesture),
        "fps": float(fps),

        "canMove": bool(can_mouse_inject and (cursor_gesture in ("OPEN_PALM", "PINCH_INDEX"))),
        "canClick": bool(
            (can_mouse_inject and (cursor_gesture in ("PINCH_INDEX", "V_SIGN")))
            or (enabled and mode_u == "VKEY")
        ),
        "scrollActive": bool(scroll_active),
        "canKey": bool(can_keyboard_inject),

        "otherGesture": str(other_gesture),

        "cursorLandmarks": _lm_to_payload(cursor_lm),
        "otherLandmarks": _lm_to_payload(other_lm),
    }

    # (선택) 디버그용: 커서손 검지끝
    if cursor_lm is not None:
        payload["cursorIndexTipX"] = float(cursor_lm[8][0])
        payload["cursorIndexTipY"] = float(cursor_lm[8][1])
        payload["cursorIndexTipZ"] = float(cursor_lm[8][2])

    # ===== AirTap event =====
    payload["tapSeq"] = int(TAP_SEQ)
    if _last_tap is not None:
        payload["tapX"] = float(_last_tap["x"])
        payload["tapY"] = float(_last_tap["y"])
        payload["tapFinger"] = int(_last_tap["finger"])
        payload["tapTs"] = float(_last_tap["ts"])

    # ===== RUSH: 양손 포인터 =====
    if rush_left is not None:
        payload["leftPointerX"] = float(rush_left["cx"])
        payload["leftPointerY"] = float(rush_left["cy"])
        payload["leftTracking"] = True
        payload["leftGesture"] = str(rush_left.get("gesture", "NONE"))
    else:
        payload["leftTracking"] = False

    if rush_right is not None:
        payload["rightPointerX"] = float(rush_right["cx"])
        payload["rightPointerY"] = float(rush_right["cy"])
        payload["rightTracking"] = True
        payload["rightGesture"] = str(rush_right.get("gesture", "NONE"))
    else:
        payload["rightTracking"] = False

    # ===== fallback pointer =====
    if rush_right is not None:
        payload["pointerX"] = float(rush_right["cx"])
        payload["pointerY"] = float(rush_right["cy"])
        payload["isTracking"] = True
    elif rush_left is not None:
        payload["pointerX"] = float(rush_left["cx"])
        payload["pointerY"] = float(rush_left["cy"])
        payload["isTracking"] = True
    elif mode_u == "VKEY" and cursor_lm is not None:
        payload["pointerX"] = float(cursor_lm[8][0])
        payload["pointerY"] = float(cursor_lm[8][1])
        payload["isTracking"] = True
    else:
        payload["isTracking"] = False

    try:
        ws.send(json.dumps(payload))
    except Exception as e:
        print("[PY] send_status error:", e)

def on_open(ws):
    global _ws_connected
    _ws_connected = True
    print("[PY] WS connected")

def on_error(ws, err):
    print("[PY] WS error:", err)

def on_close(ws, status_code, msg):
    global _ws_connected
    _ws_connected = False
    print("[PY] WS closed:", status_code, msg)

def on_message(ws, msg):
    """
    Spring -> Python CMD:
    - ENABLE / DISABLE / SET_MODE / SET_PREVIEW
    """
    global enabled, mode, locked, PREVIEW
    global _dragging, _pinch_start_ts, _pending_single_click
    global _ema_x, _ema_y

    try:
        data = json.loads(msg)
    except Exception:
        print("[PY] bad json from server:", msg)
        return

    typ = data.get("type")

    if typ == "ENABLE":
        enabled = True
        locked = False
        print("[PY] cmd ENABLE -> enabled=True")

    elif typ == "DISABLE":
        enabled = False

        if _dragging:
            try:
                pyautogui.mouseUp()
            except Exception:
                pass
            _dragging = False

        _pinch_start_ts = None
        _pending_single_click = False
        _kb_reset()
        _reset_vkey_states()
        print("[PY] cmd DISABLE -> enabled=False")

    elif typ == "SET_MODE":
        new_mode = str(data.get("mode", "MOUSE")).upper()
        apply_set_mode(new_mode)

    elif typ == "SET_PREVIEW":
        PREVIEW = bool(data.get("enabled", True))
        print("[PY] cmd SET_PREVIEW ->", PREVIEW)


# ============================================================
# Main
# ============================================================
def main():
    global PREVIEW, CONTROL_BOX, _ema_x, _ema_y, _reacquire_until
    global _last_seen_ts, _last_cursor_lm, _last_cursor_cxcy, _last_cursor_gesture
    global _dragging, _ws, _fist_start, _fist_anchor, _mod_until
    global _window_open
    global enabled, mode, locked

    print("[PY] running file:", os.path.abspath(__file__))
    print("[PY] WS_URL:", WS_URL, "(disabled)" if NO_WS else "")
    print("[PY] CURSOR_HAND_LABEL:", CURSOR_HAND_LABEL)
    print("[PY] NO_INJECT:", NO_INJECT)

    # webcam
    try:
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    except Exception:
        cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        raise RuntimeError("webcam open failed")

    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    # WS thread
    if not NO_WS:
        def ws_loop():
            global _ws
            while True:
                try:
                    ws = WebSocketApp(
                        WS_URL,
                        on_open=on_open,
                        on_close=on_close,
                        on_error=on_error,
                        on_message=on_message
                    )
                    _ws = ws
                    ws.run_forever(ping_interval=20, ping_timeout=10)
                except Exception as e:
                    print("[PY] ws_loop exception:", e)
                time.sleep(1.0)

        threading.Thread(target=ws_loop, daemon=True).start()

    prev = now()
    fps = 0.0

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            continue

        # mirror
        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        t = now()
        dt = max(t - prev, 1e-6)
        prev = t
        fps = 0.9 * fps + 0.1 * (1.0 / dt)

        # inference
        res = hands.process(rgb)
        got_any = (res.multi_hand_landmarks is not None and len(res.multi_hand_landmarks) > 0)

        cursor_lm = None
        other_lm = None

        hands_list = []
        if got_any:
            labels = []
            if res.multi_handedness:
                for h in res.multi_handedness:
                    labels.append(h.classification[0].label)
            else:
                labels = [None] * len(res.multi_hand_landmarks)

            for i, lm_obj in enumerate(res.multi_hand_landmarks):
                lm = [(p.x, p.y, p.z) for p in lm_obj.landmark]
                label = labels[i] if i < len(labels) else None
                hands_list.append((label, lm))

        # RUSH: screen-based left/right
        rush_left, rush_right = pick_lr_by_screen_x(hands_list)

        # cursor/other pick
        if hands_list:
            for label, lm in hands_list:
                if label == CURSOR_HAND_LABEL:
                    cursor_lm = lm
                    break
            if cursor_lm is None:
                cursor_lm = hands_list[0][1]

            if len(hands_list) >= 2:
                for label, lm in hands_list:
                    if lm is not cursor_lm:
                        other_lm = lm
                        break

        # cursor gesture (loss smoothing)
        got_cursor = (cursor_lm is not None)
        if got_cursor:
            cursor_cx, cursor_cy = palm_center(cursor_lm)
            if is_fist(cursor_lm):
                cursor_gesture = "FIST"
            elif is_pinch_index(cursor_lm):
                cursor_gesture = "PINCH_INDEX"
            elif is_v_sign(cursor_lm):
                cursor_gesture = "V_SIGN"
            elif is_open_palm(cursor_lm):
                cursor_gesture = "OPEN_PALM"
            else:
                cursor_gesture = "OTHER"

            _last_seen_ts = t
            _last_cursor_lm = cursor_lm
            _last_cursor_cxcy = (cursor_cx, cursor_cy)
            _last_cursor_gesture = cursor_gesture

        else:
            if _last_cursor_lm is not None and (t - _last_seen_ts) <= LOSS_GRACE_SEC:
                cursor_cx, cursor_cy = _last_cursor_cxcy
                cursor_gesture = _last_cursor_gesture
                cursor_lm = _last_cursor_lm
                got_cursor = True
            else:
                cursor_gesture = "NONE"
                cursor_cx, cursor_cy = (0.5, 0.5)

                if _dragging:
                    try:
                        pyautogui.mouseUp()
                    except Exception:
                        pass
                    _dragging = False

                if _last_cursor_lm is None or (t - _last_seen_ts) >= HARD_LOSS_SEC:
                    _reacquire_until = t + REACQUIRE_BLOCK_SEC

        # other hand
        got_other = (other_lm is not None)
        other_cx, other_cy = (0.5, 0.5)
        other_gesture = "NONE"
        other_cx, other_cy = (0.5, 0.5)
        if got_other:
            other_cx, other_cy = palm_center(other_lm)
            if is_fist(other_lm):
                other_gesture = "FIST"
            elif is_pinch_index(other_lm):
                other_gesture = "PINCH_INDEX"
            elif is_v_sign(other_lm):
                other_gesture = "V_SIGN"
            elif is_open_palm(other_lm):
                other_gesture = "OPEN_PALM"
            else:
                other_gesture = "OTHER"

        mode_u = str(mode).upper()

        # ============================================================
        # UI Mode Menu (HUD) + NEXT_MODE (gesture-based cycle)
        # ============================================================
        # (A) HUD 메뉴: 양손 FIST 홀드 -> OPEN_MODE_MENU / NAV / CONFIRM / CLOSE 이벤트를 WS로 전송
        ui_consuming = handle_ui_mode_menu(cursor_gesture, other_gesture, got_other)

        # (B) NEXT_MODE: locked 상태에서 양손 OPEN_PALM 홀드 -> NEXT_MODE 이벤트 (서버에서 모드 사이클)
        global _mode_hold_start, _last_mode_event_ts
        if enabled and locked and got_other and (cursor_gesture == "OPEN_PALM") and (other_gesture == "OPEN_PALM"):
            if _mode_hold_start is None:
                _mode_hold_start = t
            if (t - _mode_hold_start) >= MODE_HOLD_SEC and t >= (_last_mode_event_ts + MODE_COOLDOWN_SEC):
                send_event(_ws, "NEXT_MODE")
                _last_mode_event_ts = t
                _mode_hold_start = None
        else:
            _mode_hold_start = None


        # LOCK only in MOUSE
        if mode_u == "MOUSE":
            handle_lock(cursor_gesture, cursor_cx, cursor_cy, got_cursor, got_other, False)
        else:
            _fist_start = None
            _fist_anchor = None

        # injection permissions
        can_mouse_inject = enabled and (mode_u == "MOUSE") and (t >= _reacquire_until) and (not locked) and (not NO_INJECT)
        can_draw_inject  = enabled and (mode_u == "DRAW") and (t >= _reacquire_until) and (not locked) and (not NO_INJECT)
        can_keyboard_inject = enabled and (mode_u == "KEYBOARD") and (t >= _reacquire_until) and (not locked) and (not NO_INJECT)
        can_ppt_inject   = enabled and (mode_u == "PRESENTATION") and (t >= _reacquire_until) and (not locked) and (not NO_INJECT)
        # VKEY는 NO_INJECT여도 "탭 감지/이벤트"는 동작 (실제 클릭만 NO_INJECT에서 차단)
        can_vkey_inject  = enabled and (mode_u == "VKEY") and (t >= _reacquire_until) and (not locked)

        # RUSH disables OS inject
        if mode_u == "RUSH":
            can_mouse_inject = False
            can_draw_inject = False
            can_keyboard_inject = False
            can_ppt_inject = False
            can_vkey_inject = False

        # VKEY only uses vkey (mouse/keyboard/draw/ppt OFF)
        if mode_u == "VKEY":
            can_mouse_inject = False
            can_draw_inject = False
            can_keyboard_inject = False
            can_ppt_inject = False

        # pointer move (MOUSE / DRAW / PRESENTATION)
        can_pointer_inject = (can_mouse_inject or can_draw_inject or can_ppt_inject)

        if can_pointer_inject:
            do_move = False

            if mode_u == "MOUSE":
                # 마우스: OPEN_PALM 이동, 드래그 중 PINCH 이동
                do_move = (cursor_gesture == "OPEN_PALM") or (_dragging and cursor_gesture == "PINCH_INDEX")

            elif mode_u == "DRAW":
                # 그리기: OPEN_PALM 이동, PINCH는 그리기(Down) + 이동
                do_move = (cursor_gesture in ("OPEN_PALM", "PINCH_INDEX")) or _draw_down

            elif mode_u == "PRESENTATION":
                # 발표: 기본은 포인터만 이동 (OPEN_PALM)
                do_move = (cursor_gesture == "OPEN_PALM")

            if do_move:
                ux, uy = map_control_to_screen(cursor_cx, cursor_cy)
                ex, ey = apply_ema(ux, uy)
                move_cursor(ex, ey)


        # mouse actions (MOUSE only)
        if mode_u == "MOUSE":
            handle_index_pinch_click_drag(cursor_gesture, can_mouse_inject)
            handle_right_click(cursor_gesture, can_mouse_inject)
        else:
            # not mouse => clear mouse side effects
            handle_index_pinch_click_drag(cursor_gesture, False)
            handle_right_click(cursor_gesture, False)

        # DRAW (Paint/Whiteboard)
        if mode_u == "DRAW":
            handle_draw_mode(cursor_gesture, can_draw_inject)
            handle_draw_selection_shortcuts(cursor_gesture, other_gesture, got_other, can_draw_inject)
        else:
            _draw_reset()

        # PRESENTATION
        if mode_u == "PRESENTATION":
            handle_presentation_mode(
                can_ppt_inject,
                got_cursor, cursor_gesture,
                got_other, other_gesture
            )
        else:
            _ppt_reset()

        # scroll (MOUSE only: other hand FIST + vertical move)
        scroll_active = False
        if can_mouse_inject and got_other:
            handle_scroll_other_hand(other_gesture == "FIST", other_cy, True)
            scroll_active = (other_gesture == "FIST")
        else:
            handle_scroll_other_hand(False, 0.5, False)

        # keyboard
        handle_keyboard_mode(
            can_keyboard_inject,
            got_cursor, cursor_gesture,
            got_other, other_gesture
        )

        # VKEY
        if mode_u == "VKEY":
            handle_vkey_mode(can_vkey_inject, cursor_lm)

        # status
        send_status(
            _ws,
            fps,
            cursor_gesture,
            (can_mouse_inject or can_draw_inject or can_ppt_inject),
            (can_keyboard_inject or can_ppt_inject),
            scroll_active,
            other_gesture,
            rush_left=rush_left,
            rush_right=rush_right,
            cursor_lm=cursor_lm,
            other_lm=other_lm,
        )

        # preview / local keys
        if not HEADLESS:
            if PREVIEW:
                if not _window_open:
                    cv2.namedWindow("GestureOS Agent", cv2.WINDOW_NORMAL)
                    _window_open = True

                fn_on = (t < _mod_until)

                # 상단 상태
                line1 = f"mode={mode_u} enabled={enabled} locked={locked} cur={cursor_gesture} oth={other_gesture} FN={fn_on} noInject={NO_INJECT}"
                cv2.putText(frame, line1, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)

                # VKEY 안내 + tapSeq
                if mode_u == "VKEY":
                    cv2.putText(frame, "VKEY: Multi-finger AirTap (4/8/12/16/20)", (10, 50),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2)
                    cv2.putText(frame, f"tapSeq={TAP_SEQ}", (10, 75),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2)

                # RUSH debug
                if rush_left is not None:
                    cv2.putText(frame, f"RUSH L: ({rush_left['cx']:.2f},{rush_left['cy']:.2f}) {rush_left['gesture']}",
                                (10, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 2)
                if rush_right is not None:
                    cv2.putText(frame, f"RUSH R: ({rush_right['cx']:.2f},{rush_right['cy']:.2f}) {rush_right['gesture']}",
                                (10, 125), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 0, 255), 2)

                cv2.imshow("GestureOS Agent", frame)

                key = cv2.waitKey(1) & 0xFF
                if key == 27:
                    break
                elif key in (ord('e'), ord('E')):
                    globals()["enabled"] = not enabled
                    print("[KEY] enabled:", enabled)
                elif key in (ord('l'), ord('L')):
                    globals()["locked"] = not locked
                    print("[KEY] locked:", locked)
                elif key in (ord('p'), ord('P')):
                    PREVIEW = not PREVIEW
                    print("[KEY] preview:", PREVIEW)
                elif key in (ord('m'), ord('M')):
                    apply_set_mode("MOUSE")
                elif key in (ord('k'), ord('K')):
                    apply_set_mode("KEYBOARD")
                elif key in (ord('r'), ord('R')):
                    apply_set_mode("RUSH")
                elif key in (ord('v'), ord('V')):
                    apply_set_mode("VKEY")
                elif key in (ord('o'), ord('O')):
                    open_windows_osk()
                    print("[KEY] open OSK")
                elif key in (ord('c'), ord('C')):
                    cx, cy = _last_cursor_cxcy if _last_cursor_cxcy is not None else (0.5, 0.5)
                    minx = clamp01(cx - CONTROL_HALF_W)
                    maxx = clamp01(cx + CONTROL_HALF_W)
                    miny = clamp01(cy - CONTROL_HALF_H)
                    maxy = clamp01(cy + CONTROL_HALF_H)
                    globals()["CONTROL_BOX"] = (minx, miny, maxx, maxy)
                    _ema_x = None
                    _ema_y = None
                    print("[CALIB] CONTROL_BOX =", CONTROL_BOX)
            else:
                if _window_open:
                    cv2.destroyWindow("GestureOS Agent")
                    _window_open = False
                time.sleep(0.005)
        else:
            time.sleep(0.001)

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()