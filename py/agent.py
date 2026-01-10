"""
GestureOS Agent (Mouse + Keyboard + Presentation)
- Two-hand MODE toggle (CURSOR PINCH_INDEX + OTHER V_SIGN hold)  [MOUSE/KEYBOARD only]
- Two-hand NEXT_MODE event (both OPEN_PALM hold while locked)
- LOCK center-box check bugfix (cy compare maxy)
- LOCK only when enabled=True and other-hand not present

PRESENTATION(PPT) mode 목표 동작:
- 다음/이전: → / ←
- 시작/종료: F5 / Esc
- 블랙스크린: B (선택 옵션)
- 포인터: OPEN_PALM 으로 이동(클릭/드래그 없음)

추가(요청 반영):
- PPT 다음(→)을 "클랩(에어클랩)"으로 변경:
  * 양손 OPEN_PALM 상태에서 손바닥 중심 거리가 NEAR 이하로 가까워졌다가
    FAR 이상으로 멀어지는 순간 1회 clap으로 인식 -> Right Arrow
"""

import json
import time
import threading
import math
import os
import sys

import cv2
import mediapipe as mp
import pyautogui
from websocket import WebSocketApp


# ============================================================
# WebSocket
# ============================================================
WS_URL = "ws://127.0.0.1:8080/ws/agent"

HEADLESS = ("--headless" in sys.argv)
PREVIEW = not HEADLESS
_window_open = False

# 커서 제어 손(반대로 동작하면 "Left"로)
CURSOR_HAND_LABEL = "Right"

_ws = None
_ws_connected = False


# ============================================================
# Control box (normalized 0~1)
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
# Motion smoothing / jitter control
# ============================================================
EMA_ALPHA = 0.22
DEADZONE_PX = 12

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
# Runtime state from Spring
# ============================================================
enabled = False
mode = "MOUSE"
locked = True


# ============================================================
# MediaPipe
# ============================================================
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=2,
    model_complexity=1,
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

KB_COOLDOWN_SEC = {"SPACE": 0.35, "ENTER": 0.35, "ESC": 0.45}

_kb_last_token = None
_kb_streak = 0
_kb_last_repeat_ts = 0.0
_kb_last_fire_map = {"SPACE": 0.0, "ENTER": 0.0, "ESC": 0.0}
_kb_token_start_ts = 0.0
_kb_armed = True


# ============================================================
# PRESENTATION mode (PPT)
# ============================================================
# 이전: Left (V_SIGN hold)
PPT_PREV_HOLD_SEC = 0.20
PPT_COOLDOWN_SEC = 0.35

# 블랙스크린(B) - 선택
PPT_ENABLE_BLACK = True
PPT_BLACK_HOLD_SEC = 0.45
PPT_BLACK_COOLDOWN_SEC = 0.80

# 시작/종료 (F5 / Esc)
# - 시작(F5): 양손 OPEN_PALM 홀드 (클랩과의 오작동 방지: 거리조건 + inhibit 적용)
# - 종료(Esc): 양손 PINCH_INDEX 홀드
PPT_START_HOLD_SEC = 0.60
PPT_START_COOLDOWN_SEC = 1.20
PPT_END_HOLD_SEC = 0.60
PPT_END_COOLDOWN_SEC = 0.80

# ---- [NEW] NEXT by CLAP (both OPEN_PALM near->far) ----
# 튜닝 포인트:
# - 잘 안 잡히면: NEAR_DIST 올리기(0.12~0.14)
# - 너무 민감하면: NEAR_DIST 내리기(0.09~0.10) 또는 FAR_DIST 올리기(0.22~0.25)
PPT_CLAP_NEAR_DIST = 0.11
PPT_CLAP_FAR_DIST = 0.20
PPT_CLAP_MAX_CONTACT_SEC = 0.40
PPT_CLAP_COOLDOWN_SEC = 0.35

# clap 후 START(F5) 오작동 방지용 inhibit (초)
PPT_AFTER_CLAP_INHIBIT_START_SEC = 0.85

# 상태들
_ppt_v_start = None
_ppt_last_prev_ts = 0.0

_ppt_fist_start = None
_ppt_last_black_ts = 0.0

_ppt_start_hold = None
_ppt_last_start_ts = 0.0
_ppt_start_fired = False

_ppt_end_hold = None
_ppt_last_end_ts = 0.0
_ppt_end_fired = False

# clap state
_ppt_clap_contact = False
_ppt_clap_contact_ts = 0.0
_ppt_last_clap_ts = 0.0
_ppt_inhibit_start_until = 0.0


def _ppt_reset():
    global _ppt_v_start, _ppt_last_prev_ts
    global _ppt_fist_start, _ppt_last_black_ts
    global _ppt_start_hold, _ppt_last_start_ts, _ppt_start_fired
    global _ppt_end_hold, _ppt_last_end_ts, _ppt_end_fired
    global _ppt_clap_contact, _ppt_clap_contact_ts, _ppt_last_clap_ts, _ppt_inhibit_start_until

    _ppt_v_start = None
    _ppt_last_prev_ts = 0.0

    _ppt_fist_start = None
    _ppt_last_black_ts = 0.0

    _ppt_start_hold = None
    _ppt_last_start_ts = 0.0
    _ppt_start_fired = False

    _ppt_end_hold = None
    _ppt_last_end_ts = 0.0
    _ppt_end_fired = False

    _ppt_clap_contact = False
    _ppt_clap_contact_ts = 0.0
    _ppt_last_clap_ts = 0.0
    _ppt_inhibit_start_until = 0.0


# ============================================================
# Utility
# ============================================================
def now():
    return time.time()

def clamp01(v):
    return max(0.0, min(1.0, v))

def dist(a, b):
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

def move_cursor(norm_x, norm_y):
    global _last_move_ts
    t = now()
    if (t - _last_move_ts) < MOVE_INTERVAL_SEC:
        return
    _last_move_ts = t

    sx, sy = pyautogui.size()
    x = int(norm_x * sx)
    y = int(norm_y * sy)

    cur = pyautogui.position()
    if abs(x - cur.x) < DEADZONE_PX and abs(y - cur.y) < DEADZONE_PX:
        return

    pyautogui.moveTo(x, y)

def finger_extended(lm, tip, pip):
    return lm[tip][1] < lm[pip][1]


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

def is_pinch_index(lm):
    return dist(lm[4], lm[8]) < PINCH_THRESH_INDEX

def is_two_finger(lm):
    idx = finger_extended(lm, 8, 6)
    mid = finger_extended(lm, 12, 10)
    ring = finger_extended(lm, 16, 14)
    pinky = finger_extended(lm, 20, 18)
    return idx and mid and (not ring) and (not pinky)

def is_v_sign(lm):
    if not is_two_finger(lm):
        return False
    return dist(lm[8], lm[12]) > 0.06

def is_v_sign_switch(lm):
    if not is_two_finger(lm):
        return False
    return dist(lm[8], lm[12]) > 0.045


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
    global mode, locked
    global _dragging, _pinch_start_ts, _pending_single_click

    nm = str(new_mode).upper()
    if nm == "PPT":
        nm = "PRESENTATION"

    if nm not in ("MOUSE", "KEYBOARD", "PRESENTATION"):
        print("[PY] apply_set_mode ignored:", new_mode)
        return

    # leaving mouse: release drag
    if nm != "MOUSE":
        if _dragging:
            try:
                pyautogui.mouseUp()
            except Exception:
                pass
        _dragging = False
        _pinch_start_ts = None
        _pending_single_click = False

    # mode-specific resets
    if nm == "KEYBOARD":
        locked = False
        _kb_reset()
        _ppt_reset()
    elif nm == "PRESENTATION":
        locked = False
        _kb_reset()
        _ppt_reset()
    else:  # MOUSE
        _kb_reset()
        _ppt_reset()

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
        _ws.send(json.dumps({"type": "SET_MODE", "mode": m, "source": source}))
    except Exception as e:
        print("[PY] ws_send_set_mode error:", e)


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
# MODE SWITCH handler (two-hand combo hold)
# ============================================================
def handle_mode_switch_two_hand(cursor_lm, cursor_cxcy, got_cursor,
                                other_lm, other_cxcy, got_other):
    """
    CURSOR=PINCH_INDEX + OTHER=V_SIGN 를 중앙 박스에서 유지하면 MOUSE<->KEYBOARD 토글
    ⚠️ IMPORTANT: PRESENTATION 등 다른 모드에서는 절대 개입하지 않음
    return: True면(홀드 중) 입력 주입을 막아야 함
    """
    global mode, _ms_start, _ms_anchor_cur, _ms_anchor_oth, _last_mode_switch_ts, _reacquire_until

    mu = str(mode).upper()
    if mu not in ("MOUSE", "KEYBOARD"):
        _ms_start = None
        return False

    t = now()

    if t < _last_mode_switch_ts + MODE_SWITCH_COOLDOWN_SEC:
        _ms_start = None
        return False

    if not (got_cursor and got_other and cursor_lm is not None and other_lm is not None):
        _ms_start = None
        return False

    if not (is_pinch_index(cursor_lm) and is_v_sign_switch(other_lm)):
        _ms_start = None
        return False

    minx, miny, maxx, maxy = MODE_SWITCH_BOX
    cx, cy = cursor_cxcy
    ox, oy = other_cxcy
    if not (minx <= cx <= maxx and miny <= cy <= maxy and minx <= ox <= maxx and miny <= oy <= maxy):
        _ms_start = None
        return False

    if _ms_start is None:
        _ms_start = t
        _ms_anchor_cur = cursor_cxcy
        _ms_anchor_oth = other_cxcy
        return True

    if dist(cursor_cxcy, _ms_anchor_cur) > MODE_SWITCH_STILL_MAX_MOVE or dist(other_cxcy, _ms_anchor_oth) > MODE_SWITCH_STILL_MAX_MOVE:
        _ms_start = t
        _ms_anchor_cur = cursor_cxcy
        _ms_anchor_oth = other_cxcy
        return True

    if (t - _ms_start) >= MODE_SWITCH_HOLD_SEC:
        new_mode = "KEYBOARD" if mu == "MOUSE" else "MOUSE"
        apply_set_mode(new_mode)
        ws_send_set_mode(new_mode)
        _last_mode_switch_ts = t
        _ms_start = None
        _reacquire_until = t + 0.25
        return False

    return True


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
# Presentation mode
# ============================================================
def handle_presentation_mode(cursor_gesture, cursor_cxcy, other_gesture, other_cxcy, got_other, can_inject):
    """
    PRESENTATION:
      - NEXT (Right): CLAP (both OPEN_PALM near->far)
      - PREV (Left): V_SIGN hold
      - START (F5): both OPEN_PALM hold (단, 손이 충분히 떨어져 있고 clap 직후 inhibit)
      - END (Esc): both PINCH_INDEX hold (최우선)
      - BLACK (B): (optional) FIST hold
    """
    global _ppt_v_start, _ppt_last_prev_ts
    global _ppt_fist_start, _ppt_last_black_ts
    global _ppt_start_hold, _ppt_last_start_ts, _ppt_start_fired
    global _ppt_end_hold, _ppt_last_end_ts, _ppt_end_fired
    global _ppt_clap_contact, _ppt_clap_contact_ts, _ppt_last_clap_ts, _ppt_inhibit_start_until

    t = now()

    if not can_inject:
        _ppt_reset()
        return

    # ---- END (Esc): both PINCH_INDEX hold (최우선, 다른 동작 차단)
    end_combo = got_other and (cursor_gesture == "PINCH_INDEX") and (other_gesture == "PINCH_INDEX")
    if end_combo:
        if not _ppt_end_fired:
            if _ppt_end_hold is None:
                _ppt_end_hold = t
            elif (t - _ppt_end_hold) >= PPT_END_HOLD_SEC and t >= _ppt_last_end_ts + PPT_END_COOLDOWN_SEC:
                pyautogui.press("esc")
                _ppt_last_end_ts = t
                _ppt_end_fired = True
        return
    else:
        _ppt_end_hold = None
        _ppt_end_fired = False

    # ---- NEXT (Right): CLAP (both OPEN_PALM near->far)
    if got_other and (cursor_gesture == "OPEN_PALM") and (other_gesture == "OPEN_PALM"):
        d = dist(cursor_cxcy, other_cxcy)

        # contact start
        if (not _ppt_clap_contact) and d <= PPT_CLAP_NEAR_DIST:
            _ppt_clap_contact = True
            _ppt_clap_contact_ts = t

        # too long contact -> cancel (홀드/정지로 인한 오판 방지)
        if _ppt_clap_contact and (t - _ppt_clap_contact_ts) > PPT_CLAP_MAX_CONTACT_SEC:
            _ppt_clap_contact = False

        # release -> fire next
        if _ppt_clap_contact and d >= PPT_CLAP_FAR_DIST:
            _ppt_clap_contact = False
            if t >= _ppt_last_clap_ts + PPT_CLAP_COOLDOWN_SEC:
                pyautogui.press("right")
                _ppt_last_clap_ts = t
                # clap 직후 START(F5) 오작동 방지
                _ppt_inhibit_start_until = t + PPT_AFTER_CLAP_INHIBIT_START_SEC
            return  # clap으로 다음 넘겼으면 다른 동작은 이번 프레임에 막기
    else:
        _ppt_clap_contact = False

    # ---- START (F5): both OPEN_PALM hold (거리 조건 + clap 직후 inhibit)
    # clap과의 충돌 방지:
    # 1) clap 직후 inhibit 시간 동안은 시작홀드 무시
    # 2) 두 손 거리가 FAR 이상(충분히 떨어짐)일 때만 시작홀드 카운트
    start_combo = got_other and (cursor_gesture == "OPEN_PALM") and (other_gesture == "OPEN_PALM")
    if start_combo and (t >= _ppt_inhibit_start_until):
        d2 = dist(cursor_cxcy, other_cxcy)
        if d2 >= PPT_CLAP_FAR_DIST:
            if not _ppt_start_fired:
                if _ppt_start_hold is None:
                    _ppt_start_hold = t
                elif (t - _ppt_start_hold) >= PPT_START_HOLD_SEC and t >= _ppt_last_start_ts + PPT_START_COOLDOWN_SEC:
                    pyautogui.press("f5")
                    _ppt_last_start_ts = t
                    _ppt_start_fired = True
        else:
            # 너무 가까우면(start로 안 보고) 리셋
            _ppt_start_hold = None
            _ppt_start_fired = False
    else:
        _ppt_start_hold = None
        _ppt_start_fired = False

    # ---- PREV (Left): V_SIGN hold
    if cursor_gesture == "V_SIGN":
        if t < _ppt_last_prev_ts + PPT_COOLDOWN_SEC:
            _ppt_v_start = None
        else:
            if _ppt_v_start is None:
                _ppt_v_start = t
            elif (t - _ppt_v_start) >= PPT_PREV_HOLD_SEC:
                pyautogui.press("left")
                _ppt_last_prev_ts = t
                _ppt_v_start = None
    else:
        _ppt_v_start = None

    # ---- BLACK (B): FIST hold (optional)
    if PPT_ENABLE_BLACK:
        if cursor_gesture == "FIST":
            if t < _ppt_last_black_ts + PPT_BLACK_COOLDOWN_SEC:
                _ppt_fist_start = None
            else:
                if _ppt_fist_start is None:
                    _ppt_fist_start = t
                elif (t - _ppt_fist_start) >= PPT_BLACK_HOLD_SEC:
                    pyautogui.press("b")
                    _ppt_last_black_ts = t
                    _ppt_fist_start = None
        else:
            _ppt_fist_start = None
    else:
        _ppt_fist_start = None


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
    if mod_active and got_cursor:
        if cursor_gesture == "FIST":
            token = "BACKSPACE"
        elif cursor_gesture == "OPEN_PALM":
            token = "SPACE"
        elif cursor_gesture == "PINCH_INDEX":
            token = "ENTER"
        elif cursor_gesture == "V_SIGN":
            token = "ESC"

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
# WS callbacks
# ============================================================
def send_status(ws, fps, cursor_gesture, other_gesture, can_mouse_inject, can_key_inject, can_ppt_inject, scroll_active, mode_switch_block):
    if ws is None or (not _ws_connected):
        return
    payload = {
        "type": "STATUS",
        "enabled": bool(enabled),
        "mode": str(mode),
        "locked": bool(locked),
        "gesture": str(cursor_gesture),
        "fps": float(fps),
        "canMove": bool((can_mouse_inject or can_ppt_inject) and (cursor_gesture == "OPEN_PALM")),
        "canClick": bool(can_mouse_inject and (cursor_gesture in ("PINCH_INDEX", "V_SIGN"))),
        "scrollActive": bool(scroll_active),
        "canKey": bool(can_key_inject),
        "otherGesture": str(other_gesture),
        "modeSwitchHold": bool(mode_switch_block),
    }
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
    global enabled, locked, PREVIEW
    global _dragging, _pinch_start_ts, _pending_single_click

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
        _ppt_reset()
        print("[PY] cmd DISABLE -> enabled=False")

    elif typ == "SET_MODE":
        new_mode = str(data.get("mode", "MOUSE")).upper()
        if new_mode == "PPT":
            new_mode = "PRESENTATION"
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
    global _dragging, _ws, _window_open
    global _last_mode_event_ts, _mode_hold_start
    global _fist_start, _fist_anchor

    print("[PY] running file:", os.path.abspath(__file__))
    print("[PY] WS_URL:", WS_URL)
    print("[PY] CURSOR_HAND_LABEL:", CURSOR_HAND_LABEL)

    try:
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    except Exception:
        cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        raise RuntimeError("webcam open failed")

    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

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

        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        t = now()
        dt = max(t - prev, 1e-6)
        prev = t
        fps = 0.9 * fps + 0.1 * (1.0 / dt)

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
                lm = [(p.x, p.y) for p in lm_obj.landmark]
                label = labels[i] if i < len(labels) else None
                hands_list.append((label, lm))

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
        got_cursor = cursor_lm is not None
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

        # other hand gesture
        got_other = other_lm is not None
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

        # mode switch gesture (MOUSE/KEYBOARD only)
        mode_switch_block = handle_mode_switch_two_hand(
            cursor_lm, (cursor_cx, cursor_cy), got_cursor,
            other_lm, (other_cx, other_cy), got_other
        )

        # lock only in mouse
        if mode_u == "MOUSE":
            handle_lock(cursor_gesture, cursor_cx, cursor_cy, got_cursor, got_other, mode_switch_block)
        else:
            _fist_start = None
            _fist_anchor = None

        # NEXT_MODE event (both OPEN_PALM while locked)
        if enabled and locked and (cursor_gesture == "OPEN_PALM") and (other_gesture == "OPEN_PALM"):
            if _mode_hold_start is None:
                _mode_hold_start = t
            if (t - _mode_hold_start) >= MODE_HOLD_SEC and t >= _last_mode_event_ts + MODE_COOLDOWN_SEC:
                send_event(_ws, "NEXT_MODE")
                _last_mode_event_ts = t
                _mode_hold_start = None
        else:
            _mode_hold_start = None

        can_mouse_inject = enabled and (mode_u == "MOUSE") and (t >= _reacquire_until) and (not locked) and (not mode_switch_block)
        can_key_inject = enabled and (mode_u == "KEYBOARD") and (t >= _reacquire_until) and (not locked) and (not mode_switch_block)
        can_ppt_inject = enabled and (mode_u == "PRESENTATION") and (t >= _reacquire_until) and (not locked) and (not mode_switch_block)

        # cursor move (MOUSE + PRESENTATION): OPEN_PALM only
        if can_mouse_inject or can_ppt_inject:
            if cursor_gesture == "OPEN_PALM":
                ux, uy = map_control_to_screen(cursor_cx, cursor_cy)
                ex, ey = apply_ema(ux, uy)
                move_cursor(ex, ey)

        scroll_active = False

        if can_mouse_inject:
            handle_index_pinch_click_drag(cursor_gesture, True)
            handle_right_click(cursor_gesture, True)

            if got_other:
                handle_scroll_other_hand(other_gesture == "FIST", other_cy, True)
                scroll_active = (other_gesture == "FIST")
            else:
                handle_scroll_other_hand(False, 0.5, False)

        else:
            # not mouse => clear mouse side effects
            handle_index_pinch_click_drag(cursor_gesture, False)
            handle_right_click(cursor_gesture, False)
            handle_scroll_other_hand(False, 0.5, False)

        if can_key_inject:
            handle_keyboard_mode(can_key_inject, got_cursor, cursor_gesture, got_other, other_gesture)
        else:
            if mode_u != "KEYBOARD":
                _kb_reset()

        if can_ppt_inject:
            handle_presentation_mode(
                cursor_gesture, (cursor_cx, cursor_cy),
                other_gesture, (other_cx, other_cy),
                got_other, True
            )
        else:
            if mode_u != "PRESENTATION":
                _ppt_reset()

        # status
        send_status(_ws, fps, cursor_gesture, other_gesture, can_mouse_inject, can_key_inject, can_ppt_inject, scroll_active, mode_switch_block)

        # preview window
        if not HEADLESS:
            if PREVIEW:
                if not _window_open:
                    cv2.namedWindow("GestureOS Agent", cv2.WINDOW_NORMAL)
                    _window_open = True

                fn_on = (t < _mod_until)
                cv2.putText(
                    frame,
                    f"mode={mode_u} enabled={enabled} locked={locked} cur={cursor_gesture} oth={other_gesture} FN={fn_on} SW={mode_switch_block}",
                    (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 255, 0),
                    2,
                )
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
                elif key in (ord('m'), ord('M')):
                    apply_set_mode("MOUSE")
                elif key in (ord('k'), ord('K')):
                    apply_set_mode("KEYBOARD")
                elif key in (ord('p'), ord('P')):
                    apply_set_mode("PRESENTATION")
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
