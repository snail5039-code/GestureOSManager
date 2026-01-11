"""
GestureOS Agent (Mouse + Keyboard + RUSH) - FULL
================================================

이 파일 1개로 끝나는 “통짜” 버전이다.

========================
MOUSE mode
========================
- LOCK toggle (mouse only): CURSOR hand FIST hold 2s (center box + still)
- Move cursor: CURSOR hand OPEN_PALM
- Left click / Drag: CURSOR hand PINCH_INDEX
    - short tap  -> left click (double-click supported)
    - hold       -> drag (mouseDown) until release
- Right click: CURSOR hand V_SIGN hold
- Scroll: OTHER hand FIST + vertical move -> wheel scroll

========================
KEYBOARD mode (FN 레이어 + 동작별 딜레이)
========================
[기본 레이어: 한손 방향키]
- Left  : CURSOR FIST        (repeat)
- Right : CURSOR V_SIGN      (repeat)
- Up    : CURSOR PINCH_INDEX (repeat)
- Down  : CURSOR OPEN_PALM   (repeat)

[FN 레이어: OTHER PINCH_INDEX를 잡고 있는 동안 특수키]
- Backspace : CURSOR FIST        (repeat)
- Space     : CURSOR OPEN_PALM   (one-shot)
- Enter     : CURSOR PINCH_INDEX (one-shot)
- Esc       : CURSOR V_SIGN      (one-shot)

* KEYBOARD는 의도치 않은 입력 방지를 위해:
  - 토큰(동작)별 최소 유지시간(hold) + 토큰별 쿨다운 적용

========================
RUSH mode (게임 데모용)
========================
- OS 제어(마우스/키보드 주입)는 하지 않음
- 대신, "양손 포인터 좌표"를 Spring으로 계속 전송
- Rush3DPage(React)가 /api/control/status를 폴링해서
  leftPointerX/Y, rightPointerX/Y를 읽어 커서를 움직임

Local keys (OpenCV window focused)
- E: enabled toggle (test without Spring)
- L: locked toggle
- M: force mode=MOUSE
- K: force mode=KEYBOARD (unlock)
- R: force mode=RUSH (unlock)   <-- 추가
- C: calibrate CONTROL_BOX around current cursor-hand position
- ESC: exit
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
# WebSocket (Spring Boot가 열어주는 WS 엔드포인트)
# ============================================================
WS_URL = "ws://127.0.0.1:8080/ws/agent"

HEADLESS = ("--headless" in sys.argv)  # --headless 붙이면 OpenCV 프리뷰창 없이 동작
PREVIEW = not HEADLESS
_window_open = False

# 커서 제어 손(반대로 동작하면 "Left"로)
CURSOR_HAND_LABEL = "Right"

_ws = None
_ws_connected = False


# ============================================================
# Control box (normalized 0~1)
# - 손바닥 중심(cx,cy)을 이 박스 안에서만 읽고,
#   박스 -> 화면 전체(0~1)로 맵핑하여 커서를 이동
# ============================================================
CONTROL_BOX = (0.30, 0.35, 0.70, 0.92)
CONTROL_GAIN = 1.35
CONTROL_HALF_W = 0.20
CONTROL_HALF_H = 0.28


# ============================================================
# Motion smoothing / jitter control
# ============================================================
EMA_ALPHA = 0.22
DEADZONE_PX = 12

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0  # 입력 주입 지연 제거

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
# - 커서 손이 FIST 상태로 중앙 박스에서 2초 고정 => locked 토글
# ============================================================
LOCK_HOLD_SEC = 2.0
LOCK_TOGGLE_COOLDOWN_SEC = 1.0
LOCK_CENTER_BOX = (0.25, 0.15, 0.75, 0.85)
FIST_STILL_MAX_MOVE = 0.020

_fist_start = None
_fist_anchor = None
_last_lock_toggle_ts = 0.0


# ============================================================
# Tracking loss handling
# - 손 추적이 순간 끊겨도 LOSS_GRACE_SEC 동안은 마지막 값 유지
# - HARD_LOSS_SEC 지나면 "재획득 블록" 걸어서 오동작 방지
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
# - Spring에서 ENABLE / DISABLE / SET_MODE 받으면 여기 값이 바뀜
# ============================================================
enabled = False
mode = "MOUSE"
locked = True


# ============================================================
# MediaPipe Hands
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
# KEYBOARD mode (FN 레이어 + 동작별 딜레이)
# ============================================================
KB_STABLE_FRAMES = 3

# repeat token(방향키/백스페이스) 반복 속도
KB_REPEAT_SEC = 0.12

# OTHER PINCH가 잠깐 끊겨도 FN 유지
MOD_GRACE_SEC = 0.20
_mod_until = 0.0

# 토큰별 "최소 유지 시간"(초) - 즉발 방지 핵심
KB_HOLD_SEC = {
    "LEFT": 0.10,
    "RIGHT": 0.10,
    "UP": 0.10,
    "DOWN": 0.10,
    "BACKSPACE": 0.12,
    "SPACE": 0.16,
    "ENTER": 0.16,
    "ESC": 0.18,
}

# 토큰별 쿨다운(초) - one-shot 오작동 방지
KB_COOLDOWN_SEC = {
    "SPACE": 0.35,
    "ENTER": 0.35,
    "ESC": 0.45,
}

_kb_last_token = None
_kb_streak = 0

# repeat 전용(전역)
_kb_last_repeat_ts = 0.0

# one-shot 전용(토큰별)
_kb_last_fire_map = {
    "SPACE": 0.0,
    "ENTER": 0.0,
    "ESC": 0.0,
}

# 토큰 유지 시작 시각(hold 체크)
_kb_token_start_ts = 0.0

# one-shot 연타 방지(홀드 중 1회만)
_kb_armed = True


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
    """
    손바닥 중심 추정:
    - wrist(0), index_mcp(5), middle_mcp(9), ring_mcp(13), pinky_mcp(17)
    """
    idx = [0, 5, 9, 13, 17]
    xs = [lm[i][0] for i in idx]
    ys = [lm[i][1] for i in idx]
    return (sum(xs) / len(xs), sum(ys) / len(ys))

def map_control_to_screen(cx, cy):
    """
    CONTROL_BOX(부분 박스) 안에서의 cx,cy를
    화면 전체 normalized(0~1)로 맵핑
    """
    minx, miny, maxx, maxy = CONTROL_BOX
    ux = (cx - minx) / max(1e-6, (maxx - minx))
    uy = (cy - miny) / max(1e-6, (maxy - miny))
    ux = clamp01(ux)
    uy = clamp01(uy)
    ux = 0.5 + (ux - 0.5) * CONTROL_GAIN
    uy = 0.5 + (uy - 0.5) * CONTROL_GAIN
    return clamp01(ux), clamp01(uy)

def apply_ema(nx, ny):
    """
    좌표 EMA 스무딩(손 떨림 완화)
    """
    global _ema_x, _ema_y
    if _ema_x is None:
        _ema_x, _ema_y = nx, ny
    else:
        _ema_x = EMA_ALPHA * nx + (1.0 - EMA_ALPHA) * _ema_x
        _ema_y = EMA_ALPHA * ny + (1.0 - EMA_ALPHA) * _ema_y
    return _ema_x, _ema_y

def move_cursor(norm_x, norm_y):
    """
    OS 커서 이동 (normalized 0~1 -> screen pixel)
    - 너무 잦은 이동 방지(MOVE_INTERVAL_SEC)
    - DEADZONE_PX 이하면 무시(미세 떨림 무시)
    """
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
    """
    손가락이 펴져있는지(단순 판정):
    - tip y가 pip y보다 위쪽이면(작으면) 펴졌다고 판단
    """
    return lm[tip][1] < lm[pip][1]


# ============================================================
# Gesture detection (안정 포즈만)
# ============================================================
def is_fist(lm):
    tips = [8, 12, 16, 20]
    pips = [6, 10, 14, 18]
    folded = 0
    for t, p in zip(tips, pips):
        if lm[t][1] > lm[p][1]:
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


# ============================================================
# (RUSH 추가) Rush용: 제스처 분류 + 화면 기준 좌/우 손 선택
# ============================================================
def classify_gesture(lm):
    """
    Rush/Status 전송용 제스처 문자열.
    Rush3D에서는 gesture 자체를 안 써도 되지만(포인터 좌표가 핵심),
    디버깅을 위해 leftGesture/rightGesture도 같이 전송할 수 있게 해둠.
    """
    if lm is None:
        return "NONE"
    if is_fist(lm):
        return "FIST"
    if is_pinch_index(lm):
        return "PINCH_INDEX"
    if is_v_sign(lm):
        return "V_SIGN"
    if is_open_palm(lm):
        return "OPEN_PALM"
    return "OTHER"

def pick_lr_by_screen_x(hands_list):
    """
    hands_list: [(label, lm), ...]
      - lm: [(x,y), ...] normalized (0~1)

    반환:
      - left_pack, right_pack
      - pack: {"cx": float, "cy": float, "gesture": str}

    규칙:
      - 손 2개면 cx(화면 x) 기준으로 작은 손이 left, 큰 손이 right
      - 손 1개면 right만 채우고 left는 None (Rush3D에서 단일 입력 fallback 가능)
    """
    if not hands_list:
        return None, None

    packs = []
    for label, lm in hands_list:
        cx, cy = palm_center(lm)
        packs.append({
            "cx": cx,
            "cy": cy,
            "gesture": classify_gesture(lm),
        })

    packs.sort(key=lambda p: p["cx"])

    if len(packs) >= 2:
        return packs[0], packs[-1]
    else:
        return None, packs[0]


# ============================================================
# LOCK handler (mouse only)
# ============================================================
def handle_lock(cursor_gesture, cx, cy, got_cursor_hand):
    """
    - 중앙 박스(LOCK_CENTER_BOX) 안에서
    - FIST를 2초 유지 + 손이 거의 안 움직이면
    -> locked 토글
    """
    global locked, _fist_start, _fist_anchor, _last_lock_toggle_ts, _reacquire_until
    t = now()

    if not got_cursor_hand:
        _fist_start = None
        _fist_anchor = None
        return

    if t < _last_lock_toggle_ts + LOCK_TOGGLE_COOLDOWN_SEC:
        _fist_start = None
        _fist_anchor = None
        return

    minx, miny, maxx, maxy = LOCK_CENTER_BOX

    # ✅ 버그 수정 포인트:
    # 기존에 "miny <= cy <= maxx"로 되어 있으면 y판정이 깨짐.
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
# Mouse: Click / Drag (cursor hand pinch index)
# ============================================================
def handle_index_pinch_click_drag(cursor_gesture, can_inject):
    global _pinch_start_ts, _dragging, _last_click_ts
    global _pending_single_click, _single_click_deadline

    t = now()

    # 주입 불가능이면 드래그 상태 등 정리
    if not can_inject:
        if _dragging:
            try:
                pyautogui.mouseUp()
            except:
                pass
            _dragging = False
        _pinch_start_ts = None
        _pending_single_click = False
        return

    # 단일클릭 대기(더블클릭 갭 지나면 확정)
    if _pending_single_click and t >= _single_click_deadline:
        if t >= _last_click_ts + CLICK_COOLDOWN_SEC:
            pyautogui.click()
            _last_click_ts = t
        _pending_single_click = False

    if cursor_gesture == "PINCH_INDEX":
        if _pinch_start_ts is None:
            _pinch_start_ts = t

        # 홀드 → 드래그
        if (not _dragging) and (t - _pinch_start_ts >= DRAG_HOLD_SEC):
            pyautogui.mouseDown()
            _dragging = True

    else:
        # PINCH 해제 순간: 탭/드래그 종료 판정
        if _pinch_start_ts is not None:
            dur = t - _pinch_start_ts

            if _dragging:
                pyautogui.mouseUp()
                _dragging = False
            else:
                if dur <= CLICK_TAP_MAX_SEC:
                    if _pending_single_click:
                        # 두 번째 탭이면 더블클릭
                        _pending_single_click = False
                        if t >= _last_click_ts + CLICK_COOLDOWN_SEC:
                            pyautogui.doubleClick()
                            _last_click_ts = t
                    else:
                        # 첫 탭이면 더블클릭 대기 상태로 전환
                        _pending_single_click = True
                        _single_click_deadline = t + DOUBLECLICK_GAP_SEC

        _pinch_start_ts = None


# ============================================================
# Mouse: Right click (cursor hand V sign hold)
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
# Mouse: Scroll (other hand fist + y movement)
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
# Keyboard mode: FN Layer + per-action delay
# ============================================================
def _kb_reset():
    global _kb_last_token, _kb_streak, _kb_last_repeat_ts, _kb_token_start_ts, _kb_armed
    global _mod_until
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
    if token == "LEFT":
        pyautogui.press("left")
    elif token == "RIGHT":
        pyautogui.press("right")
    elif token == "UP":
        pyautogui.press("up")
    elif token == "DOWN":
        pyautogui.press("down")
    elif token == "BACKSPACE":
        pyautogui.press("backspace")
    elif token == "SPACE":
        pyautogui.press("space")
    elif token == "ENTER":
        pyautogui.press("enter")
    elif token == "ESC":
        pyautogui.press("esc")

def handle_keyboard_mode(can_inject,
                         got_cursor, cursor_gesture, cursor_cxcy,
                         got_other, other_gesture, other_cxcy):
    global _kb_last_token, _kb_streak, _kb_last_repeat_ts, _kb_token_start_ts, _kb_armed
    global _mod_until

    t = now()

    if not can_inject:
        _kb_reset()
        return

    # FN(Modifier): OTHER PINCH_INDEX 유지 (끊김 완화)
    if got_other and other_gesture == "PINCH_INDEX":
        _mod_until = t + MOD_GRACE_SEC
    mod_active = (t < _mod_until)

    token = None

    # FN 레이어(특수키)
    if mod_active and got_cursor:
        if cursor_gesture == "FIST":
            token = "BACKSPACE"      # repeat
        elif cursor_gesture == "OPEN_PALM":
            token = "SPACE"          # one-shot
        elif cursor_gesture == "PINCH_INDEX":
            token = "ENTER"          # one-shot
        elif cursor_gesture == "V_SIGN":
            token = "ESC"            # one-shot

    # 기본 레이어(방향키)
    if token is None and got_cursor:
        if cursor_gesture == "FIST":
            token = "LEFT"
        elif cursor_gesture == "V_SIGN":
            token = "RIGHT"
        elif cursor_gesture == "PINCH_INDEX":
            token = "UP"
        elif cursor_gesture == "OPEN_PALM":
            token = "DOWN"

    # 토큰 없으면 리셋(재무장)
    if token is None:
        _kb_last_token = None
        _kb_streak = 0
        _kb_token_start_ts = 0.0
        _kb_armed = True
        return

    # stable frames + 토큰 시작 시각
    if token == _kb_last_token:
        _kb_streak += 1
    else:
        _kb_last_token = token
        _kb_streak = 1
        _kb_armed = True
        _kb_token_start_ts = t

    if _kb_streak < KB_STABLE_FRAMES:
        return

    # 동작별 최소 유지 시간(hold) 체크
    need_hold = KB_HOLD_SEC.get(token, 0.12)
    if (t - _kb_token_start_ts) < need_hold:
        return

    repeat_tokens = {"LEFT", "RIGHT", "UP", "DOWN", "BACKSPACE"}
    one_shot_tokens = {"SPACE", "ENTER", "ESC"}

    # 반복 토큰: 홀드 반복
    if token in repeat_tokens:
        if t >= _kb_last_repeat_ts + KB_REPEAT_SEC:
            _fire_token(token)
            _kb_last_repeat_ts = t
        return

    # 단발 토큰: 토큰별 쿨다운 + 동일 홀드 1회만
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
def send_status(
    ws,
    fps,
    cursor_gesture,
    can_mouse_inject,
    can_keyboard_inject,
    scroll_active,
    other_gesture,
    rush_left=None,   # ✅ RUSH: 화면 기준 왼손 pack
    rush_right=None,  # ✅ RUSH: 화면 기준 오른손 pack
):
    """
    Spring이 STATUS를 저장해두고, 프론트(/api/control/status)에서 polling 한다고 가정.
    Rush3D가 읽는 키:
      - leftPointerX/Y, leftTracking
      - rightPointerX/Y, rightTracking
      - (fallback) pointerX/Y, isTracking
    """
    if ws is None or (not _ws_connected):
        return

    payload = {
        "type": "STATUS",
        "enabled": bool(enabled),
        "mode": str(mode),
        "locked": bool(locked),

        # 디버깅/표시용
        "gesture": str(cursor_gesture),
        "fps": float(fps),

        # 기존 플래그
        "canMove": bool(can_mouse_inject and (cursor_gesture in ("OPEN_PALM", "PINCH_INDEX"))),
        "canClick": bool(can_mouse_inject and (cursor_gesture in ("PINCH_INDEX", "V_SIGN"))),
        "scrollActive": bool(scroll_active),
        "canKey": bool(can_keyboard_inject),
        "otherGesture": str(other_gesture),
    }

    # ===== RUSH/FRONT에서 쓰는 “양손 포인터” =====
    # left
    if rush_left is not None:
        payload["leftPointerX"] = float(rush_left["cx"])
        payload["leftPointerY"] = float(rush_left["cy"])
        payload["leftTracking"] = True
        payload["leftGesture"] = str(rush_left.get("gesture", "NONE"))
    else:
        payload["leftTracking"] = False

    # right
    if rush_right is not None:
        payload["rightPointerX"] = float(rush_right["cx"])
        payload["rightPointerY"] = float(rush_right["cy"])
        payload["rightTracking"] = True
        payload["rightGesture"] = str(rush_right.get("gesture", "NONE"))
    else:
        payload["rightTracking"] = False

    # fallback 단일 포인터(한 손만 있어도 프론트에서 움직이게)
    if rush_right is not None:
        payload["pointerX"] = float(rush_right["cx"])
        payload["pointerY"] = float(rush_right["cy"])
        payload["isTracking"] = True
    elif rush_left is not None:
        payload["pointerX"] = float(rush_left["cx"])
        payload["pointerY"] = float(rush_left["cy"])
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
    Spring -> Python으로 오는 제어 명령 처리
    - ENABLE / DISABLE / SET_MODE / SET_PREVIEW
    """
    global enabled, mode, locked, PREVIEW
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

        # 드래그 붙는 것 방지
        if _dragging:
            try:
                pyautogui.mouseUp()
            except:
                pass
            _dragging = False
        _pinch_start_ts = None
        _pending_single_click = False

        _kb_reset()
        print("[PY] cmd DISABLE -> enabled=False")

    elif typ == "SET_MODE":
        new_mode = str(data.get("mode", "MOUSE")).upper()

        # MOUSE 아닌 모드로 갈 때 마우스 상태 정리
        if new_mode != "MOUSE":
            if _dragging:
                try:
                    pyautogui.mouseUp()
                except:
                    pass
                _dragging = False
            _pinch_start_ts = None
            _pending_single_click = False

        # KEYBOARD / RUSH 들어가면 잠금 해제 + 키보드 상태 초기화(안전)
        if new_mode in ("KEYBOARD", "RUSH"):
            locked = False
            _kb_reset()

        # KEYBOARD가 아니면 키보드 상태는 항상 초기화
        if new_mode != "KEYBOARD":
            _kb_reset()

        mode = new_mode
        print("[PY] cmd SET_MODE ->", mode)

    elif typ == "SET_PREVIEW":
        PREVIEW = bool(data.get("enabled", True))
        print("[PY] cmd SET_PREVIEW ->", PREVIEW)


# ============================================================
# Main
# ============================================================
def main():
    global enabled, mode, locked, PREVIEW, CONTROL_BOX, _ema_x, _ema_y, _reacquire_until
    global _last_seen_ts, _last_cursor_lm, _last_cursor_cxcy, _last_cursor_gesture
    global _dragging, HEADLESS
    global _ws
    global _fist_start, _fist_anchor

    print("[PY] running file:", os.path.abspath(__file__))
    print("[PY] WS_URL:", WS_URL)
    print("[PY] CURSOR_HAND_LABEL:", CURSOR_HAND_LABEL)

    # 카메라 오픈
    try:
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    except Exception:
        cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        raise RuntimeError("webcam open failed")

    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    # WS 연결은 별도 스레드에서 계속 유지
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

        # 미러(사용자 입장에선 거울이 편함)
        frame = cv2.flip(frame, 1)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        t = now()
        dt = max(t - prev, 1e-6)
        prev = t
        fps = 0.9 * fps + 0.1 * (1.0 / dt)

        # MediaPipe Hands 추론
        res = hands.process(rgb)
        got_any = (res.multi_hand_landmarks is not None and len(res.multi_hand_landmarks) > 0)

        cursor_lm = None
        other_lm = None

        # hands_list: [(label, lm), ...]
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

        # ===== (RUSH) 화면 기준 좌/우 손 pack 만들기 =====
        # - Rush3D는 "이 값들"을 Spring status에서 읽어간다.
        rush_left, rush_right = pick_lr_by_screen_x(hands_list)

        # cursor/other 손 결정(기존 방식 유지)
        if hands_list:
            # cursor hand: CURSOR_HAND_LABEL 우선
            for label, lm in hands_list:
                if label == CURSOR_HAND_LABEL:
                    cursor_lm = lm
                    break
            if cursor_lm is None:
                cursor_lm = hands_list[0][1]

            # other hand: cursor가 아닌 나머지
            if len(hands_list) >= 2:
                for label, lm in hands_list:
                    if lm is not cursor_lm:
                        other_lm = lm
                        break

        # ---------- cursor hand gesture (loss smoothing) ----------
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
            # 손 추적이 끊겨도 잠깐은 마지막 값 유지
            if _last_cursor_lm is not None and (t - _last_seen_ts) <= LOSS_GRACE_SEC:
                cursor_cx, cursor_cy = _last_cursor_cxcy
                cursor_gesture = _last_cursor_gesture
            else:
                cursor_gesture = "NONE"
                cursor_cx, cursor_cy = (0.5, 0.5)

                # 드래그 상태가 남아있으면 강제 해제
                if _dragging:
                    try:
                        pyautogui.mouseUp()
                    except:
                        pass
                    _dragging = False

                # HARD_LOSS 지나면 재획득 블록
                if _last_cursor_lm is None or (t - _last_seen_ts) >= HARD_LOSS_SEC:
                    _reacquire_until = t + REACQUIRE_BLOCK_SEC

        # ---------- other hand gesture ----------
        got_other = other_lm is not None
        other_cx, other_cy = (0.5, 0.5)
        other_gesture = "NONE"
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

        # LOCK은 MOUSE에서만 (키보드/RUSH에서 FIST와 충돌 방지)
        if mode_u == "MOUSE":
            handle_lock(cursor_gesture, cursor_cx, cursor_cy, got_cursor)
        else:
            _fist_start = None
            _fist_anchor = None

        # 주입 권한(재획득 블록, locked, enabled 고려)
        can_mouse_inject = (
            enabled and (mode_u == "MOUSE") and (t >= _reacquire_until) and (not locked)
        )
        can_keyboard_inject = (
            enabled and (mode_u == "KEYBOARD") and (t >= _reacquire_until) and (not locked)
        )

        # RUSH는 OS에 마우스/키보드 입력 주입을 하지 않도록 유지
        if mode_u == "RUSH":
            can_mouse_inject = False
            can_keyboard_inject = False

        # ---------- mouse move ----------
        if can_mouse_inject:
            if cursor_gesture == "OPEN_PALM" or (_dragging and cursor_gesture == "PINCH_INDEX"):
                ux, uy = map_control_to_screen(cursor_cx, cursor_cy)
                ex, ey = apply_ema(ux, uy)
                move_cursor(ex, ey)

        # ---------- mouse actions ----------
        handle_index_pinch_click_drag(cursor_gesture, can_mouse_inject)
        handle_right_click(cursor_gesture, can_mouse_inject)

        # ---------- scroll (mouse only) ----------
        if can_mouse_inject and got_other:
            handle_scroll_other_hand(other_gesture == "FIST", other_cy, True)
            scroll_active = (other_gesture == "FIST")
        else:
            handle_scroll_other_hand(False, 0.5, False)
            scroll_active = False

        # ---------- keyboard actions ----------
        handle_keyboard_mode(
            can_keyboard_inject,
            got_cursor, cursor_gesture, (cursor_cx, cursor_cy),
            got_other, other_gesture, (other_cx, other_cy)
        )

        # ---------- status (핵심: RUSH 포인터 포함해서 전송) ----------
        send_status(
            _ws,
            fps,
            cursor_gesture,
            can_mouse_inject,
            can_keyboard_inject,
            scroll_active,
            other_gesture,
            rush_left=rush_left,
            rush_right=rush_right,
        )

        # ---------- view / local keys ----------
        if not HEADLESS:
            global _window_open

            if PREVIEW:
                if not _window_open:
                    cv2.namedWindow("GestureOS Agent", cv2.WINDOW_NORMAL)
                    _window_open = True

                # FN 표시(디버깅용)
                fn_on = (t < _mod_until)
                cv2.putText(
                    frame,
                    f"mode={mode_u} enabled={enabled} locked={locked} cur={cursor_gesture} oth={other_gesture} FN={fn_on}",
                    (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 255, 0),
                    2,
                )

                # RUSH 좌/우 손 상태도 확인용으로 표시
                if rush_left is not None:
                    cv2.putText(
                        frame,
                        f"RUSH L: ({rush_left['cx']:.2f},{rush_left['cy']:.2f}) {rush_left['gesture']}",
                        (10, 50),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (255, 255, 0),
                        2,
                    )
                if rush_right is not None:
                    cv2.putText(
                        frame,
                        f"RUSH R: ({rush_right['cx']:.2f},{rush_right['cy']:.2f}) {rush_right['gesture']}",
                        (10, 75),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (255, 0, 255),
                        2,
                    )

                cv2.imshow("GestureOS Agent", frame)

                key = cv2.waitKey(1) & 0xFF
                if key == 27:
                    break
                elif key in (ord('e'), ord('E')):
                    enabled = not enabled
                    print("[KEY] enabled:", enabled)
                elif key in (ord('l'), ord('L')):
                    locked = not locked
                    print("[KEY] locked:", locked)
                elif key in (ord('m'), ord('M')):
                    mode = "MOUSE"
                    print("[KEY] mode=MOUSE")
                elif key in (ord('k'), ord('K')):
                    mode = "KEYBOARD"
                    locked = False
                    _kb_reset()
                    print("[KEY] mode=KEYBOARD (unlock)")
                elif key in (ord('r'), ord('R')):
                    mode = "RUSH"
                    locked = False
                    _kb_reset()
                    print("[KEY] mode=RUSH (unlock)")
                elif key in (ord('c'), ord('C')):
                    # 현재 커서 손 위치를 중심으로 control box 재설정
                    cx, cy = _last_cursor_cxcy if _last_cursor_cxcy is not None else (0.5, 0.5)
                    minx = clamp01(cx - CONTROL_HALF_W)
                    maxx = clamp01(cx + CONTROL_HALF_W)
                    miny = clamp01(cy - CONTROL_HALF_H)
                    maxy = clamp01(cy + CONTROL_HALF_H)
                    CONTROL_BOX = (minx, miny, maxx, maxy)
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
