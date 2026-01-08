"""
GestureOS Agent (Mouse) - FULL (Two-hand scroll)

Mapping
- LOCK toggle (global): CURSOR hand FIST hold 2s (center box + still)
- Move cursor: CURSOR hand OPEN_PALM (index+middle+ring+pinky extended)
- Left click / Drag: CURSOR hand PINCH_INDEX
    - short tap  -> left click
    - hold       -> drag (mouseDown) until release
- Right click: CURSOR hand V_SIGN hold
- Scroll: OTHER hand FIST + vertical move -> wheel scroll

Keys
- E: enabled toggle (test without Spring)
- L: locked toggle
- M: force mode=MOUSE
- C: calibrate CONTROL_BOX around current cursor-hand position
- ESC: exit
"""

import json
import time
import threading
import math
import os

import cv2
import mediapipe as mp
import pyautogui

from websocket import WebSocketApp


# ============================================================
# WebSocket
# ============================================================
WS_URL = "ws://127.0.0.1:8080/ws/agent"

# 커서 제어를 "오른손"으로 고정 (반대로 동작하면 "Left"로 변경)
CURSOR_HAND_LABEL = "Right"

_ws = None

# ============================================================
# Control box (normalized 0~1)
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
# PINCH / Click / Drag
# ============================================================
PINCH_THRESH_INDEX = 0.06

CLICK_TAP_MAX_SEC = 0.22
DRAG_HOLD_SEC = 0.28
CLICK_COOLDOWN_SEC = 0.30

_last_click_ts = 0.0
_pinch_start_ts = None
_dragging = False

DOUBLECLICK_GAP_SEC = 0.35   # 두 번째 탭 허용 시간(0.30~0.45 추천)
_pending_single_click = False
_single_click_deadline = 0.0

# ============================================================
# Right click (V sign)
# ============================================================
RIGHTCLICK_HOLD_SEC = 0.35
RIGHTCLICK_COOLDOWN_SEC = 0.60
_last_rightclick_ts = 0.0
_vsign_start = None


# ============================================================
# Scroll (OTHER hand fist + y movement)
# ============================================================
SCROLL_GAIN = 1400
SCROLL_DEADZONE = 0.012
SCROLL_INTERVAL_SEC = 0.05
_last_scroll_ts = 0.0
_scroll_anchor_y = None


# ============================================================
# LOCK (cursor-hand fist hold)
# ============================================================
LOCK_HOLD_SEC = 2.0
LOCK_TOGGLE_COOLDOWN_SEC = 1.0
LOCK_CENTER_BOX = (0.25, 0.15, 0.75, 0.85)
FIST_STILL_MAX_MOVE = 0.020

_fist_start = None
_fist_anchor = None
_last_lock_toggle_ts = 0.0


# ============================================================
# Tracking loss handling (cursor hand 중심)
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

_ws_connected = False


# ============================================================
# MediaPipe
# ============================================================
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=2,  # ✅ two hands
    model_complexity=1,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)


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
# Gesture detection (cursor hand 기준)
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
# LOCK handler (cursor hand)
# ============================================================
def handle_lock(cursor_gesture, cx, cy, got_cursor_hand):
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
# Click / Drag (cursor hand pinch index)
# ============================================================
def handle_index_pinch_click_drag(cursor_gesture, can_inject):
    """
    PINCH_INDEX:
      - 짧은 탭 1회: (지연 후) 단일 클릭
      - 짧은 탭 2회(시간 내): 더블클릭
      - 홀드: 드래그(mouseDown) 유지
    """
    global _pinch_start_ts, _dragging, _last_click_ts
    global _pending_single_click, _single_click_deadline

    t = now()

    # 입력 불가면 드래그 해제 + 대기 클릭 취소
    if not can_inject:
        if _dragging:
            pyautogui.mouseUp()
            _dragging = False
        _pinch_start_ts = None
        _pending_single_click = False
        return

    # ✅ 대기 중인 단일 클릭이 있고, 더블클릭 기회가 지나면 단일 클릭 확정
    if _pending_single_click and t >= _single_click_deadline:
        if t >= _last_click_ts + CLICK_COOLDOWN_SEC:
            pyautogui.click()
            _last_click_ts = t
        _pending_single_click = False

    if cursor_gesture == "PINCH_INDEX":
        if _pinch_start_ts is None:
            _pinch_start_ts = t

        # 홀드 → 드래그 시작
        if (not _dragging) and (t - _pinch_start_ts >= DRAG_HOLD_SEC):
            pyautogui.mouseDown()
            _dragging = True

    else:
        # PINCH 해제 시점에서 탭/드래그 종료 처리
        if _pinch_start_ts is not None:
            dur = t - _pinch_start_ts

            if _dragging:
                pyautogui.mouseUp()
                _dragging = False
            else:
                # 짧은 탭이면 클릭/더블클릭 판정
                if dur <= CLICK_TAP_MAX_SEC:
                    # 더블클릭 후보: 이미 단일 클릭 대기 중이면 -> 더블클릭 확정
                    if _pending_single_click:
                        _pending_single_click = False
                        if t >= _last_click_ts + CLICK_COOLDOWN_SEC:
                            pyautogui.doubleClick()
                            _last_click_ts = t
                    else:
                        # 첫 탭: 바로 클릭하지 말고 잠깐 대기(두 번째 탭 기다림)
                        _pending_single_click = True
                        _single_click_deadline = t + DOUBLECLICK_GAP_SEC

        _pinch_start_ts = None



# ============================================================
# Right click (cursor hand V sign hold)
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
# Scroll (other hand fist + y movement)
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
# WS callbacks
# ============================================================
def send_status(ws, fps, cursor_gesture, can_inject, scroll_active):
    if ws is None or (not _ws_connected):
        return
    payload = {
        "type": "STATUS",
        "enabled": bool(enabled),
        "mode": str(mode),
        "locked": bool(locked),
        "gesture": str(cursor_gesture),
        "fps": float(fps),
        "canMove": bool(can_inject and (cursor_gesture in ("OPEN_PALM", "PINCH_INDEX"))),
        "canClick": bool(can_inject and (cursor_gesture in ("PINCH_INDEX", "V_SIGN"))),
        "scrollActive": bool(scroll_active),
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
    global enabled, mode
    try:
        data = json.loads(msg)
    except Exception:
        print("[PY] bad json from server:", msg)
        return

    t = data.get("type")
    if t == "ENABLE":
        enabled = True
        print("[PY] cmd ENABLE -> enabled=True")
    elif t == "DISABLE":
        enabled = False
        print("[PY] cmd DISABLE -> enabled=False")
    elif t == "SET_MODE":
        mode = str(data.get("mode", "MOUSE")).upper()
        print("[PY] cmd SET_MODE ->", mode)


# ============================================================
# Main
# ============================================================
def main():
    global enabled, mode, locked, CONTROL_BOX, _ema_x, _ema_y, _reacquire_until
    global _last_seen_ts, _last_cursor_lm, _last_cursor_cxcy, _last_cursor_gesture
    global _dragging

    print("[PY] running file:", os.path.abspath(__file__))
    print("[PY] WS_URL:", WS_URL)
    print("[PY] CURSOR_HAND_LABEL:", CURSOR_HAND_LABEL)

    # camera
    try:
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    except Exception:
        cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        raise RuntimeError("webcam open failed")

    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    # websocket
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
                _ws = ws  # ✅ 메인 루프가 참조할 수 있게 저장
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
        scroll_lm = None
        cursor_label = None
        scroll_label = None

        # ---------- build (label, lm) list ----------
        hands_list = []
        if got_any:
            labels = []
            if res.multi_handedness:
                for h in res.multi_handedness:
                    labels.append(h.classification[0].label)  # "Left"/"Right"
            else:
                labels = [None] * len(res.multi_hand_landmarks)

            for i, lm_obj in enumerate(res.multi_hand_landmarks):
                lm = [(p.x, p.y) for p in lm_obj.landmark]
                label = labels[i] if i < len(labels) else None
                hands_list.append((label, lm))

        # ---------- choose cursor hand ----------
        if hands_list:
            # prefer configured label
            for label, lm in hands_list:
                if label == CURSOR_HAND_LABEL:
                    cursor_lm = lm
                    cursor_label = label
                    break
            # fallback: first
            if cursor_lm is None:
                cursor_label, cursor_lm = hands_list[0]

            # scroll hand: the other one if exists
            if len(hands_list) >= 2:
                for label, lm in hands_list:
                    if lm is not cursor_lm:
                        scroll_label, scroll_lm = label, lm
                        break

        # ---------- cursor center + gesture with loss smoothing ----------
        got_cursor = cursor_lm is not None
        if got_cursor:
            cursor_cx, cursor_cy = palm_center(cursor_lm)

            # gesture priority
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
            # short loss: keep last gesture/pos but don't treat as "got_cursor" for lock timers
            if _last_cursor_lm is not None and (t - _last_seen_ts) <= LOSS_GRACE_SEC:
                cursor_cx, cursor_cy = _last_cursor_cxcy
                cursor_gesture = _last_cursor_gesture
            else:
                cursor_gesture = "NONE"
                cursor_cx, cursor_cy = (0.5, 0.5)
                if _dragging:
                    pyautogui.mouseUp()
                    _dragging = False
                if _last_cursor_lm is None or (t - _last_seen_ts) >= HARD_LOSS_SEC:
                    _reacquire_until = t + REACQUIRE_BLOCK_SEC

        # ---------- other hand scroll state ----------
        scroll_active = False
        scroll_cy = None
        if scroll_lm is not None:
            _, scroll_cy = palm_center(scroll_lm)
            scroll_active = is_fist(scroll_lm)

        # ---------- LOCK ----------
        handle_lock(cursor_gesture, cursor_cx, cursor_cy, got_cursor)

        # ---------- inject condition ----------
        can_inject = (
            enabled
            and (str(mode).upper() == "MOUSE")
            and (t >= _reacquire_until)
            and (not locked)
        )

        # ---------- Move cursor (OPEN_PALM or while dragging PINCH) ----------
        if can_inject:
            if cursor_gesture == "OPEN_PALM" or (_dragging and cursor_gesture == "PINCH_INDEX"):
                ux, uy = map_control_to_screen(cursor_cx, cursor_cy)
                ex, ey = apply_ema(ux, uy)
                move_cursor(ex, ey)

        # ---------- Click/Drag ----------
        handle_index_pinch_click_drag(cursor_gesture, can_inject)

        # ---------- Right click ----------
        handle_right_click(cursor_gesture, can_inject)

        # ---------- Scroll (other hand fist) ----------
        if scroll_cy is None:
            handle_scroll_other_hand(False, 0.5, can_inject)
        else:
            handle_scroll_other_hand(scroll_active, scroll_cy, can_inject)

        # ---------- status + overlay ----------
        send_status(_ws, fps, cursor_gesture, can_inject, scroll_active)

        cv2.putText(frame, f"enabled={enabled} mode={mode} locked={locked}", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(frame, f"cursor={cursor_label} gesture={cursor_gesture} fps={fps:.1f}", (10, 55),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
        cv2.putText(frame, f"scroll={scroll_label} active={scroll_active}", (10, 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
        cv2.putText(frame, f"can_inject={can_inject} wait={(max(0.0, _reacquire_until - t)):.2f}s", (10, 105),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(frame, f"BOX={CONTROL_BOX} GAIN={CONTROL_GAIN}", (10, 130),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)

        cv2.imshow("GestureOS Agent", frame)

        # ---------- keys ----------
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
        elif key in (ord('c'), ord('C')):
            # calibrate around current cursor center (even if last known)
            cx, cy = _last_cursor_cxcy if _last_cursor_cxcy is not None else (0.5, 0.5)
            minx = clamp01(cx - CONTROL_HALF_W)
            maxx = clamp01(cx + CONTROL_HALF_W)
            miny = clamp01(cy - CONTROL_HALF_H)
            maxy = clamp01(cy + CONTROL_HALF_H)
            CONTROL_BOX = (minx, miny, maxx, maxy)
            _ema_x = None
            _ema_y = None
            print("[CALIB] CONTROL_BOX =", CONTROL_BOX)

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
