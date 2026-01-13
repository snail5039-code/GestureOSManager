"""
rush_color_agent_robust.py
- OpenCV HSV 기반 "봉 색" 트래킹 (RED / BLUE)
- contour의 top-most point(끝점) 기반으로 좌표 산출 (빠른 상하 움직임에 유리)
- 스무딩 약화 + 트래킹 드랍 grace + 레인 고정(BLUE=Left, RED=Right)
- WebSocket(Spring)으로 STATUS 전송 (RUSH용)

Keys (preview window focus):
  ESC : quit
  E   : enabled toggle
  P   : PREVIEW toggle
  T   : HSV tuner toggle (trackbar)
  D   : print HSV ranges
  1   : calibrate RED from center ROI
  2   : calibrate BLUE from center ROI
"""

import json
import time
import threading

import cv2
import numpy as np
from websocket import WebSocketApp

# =========================
# WS (Spring Boot)
# =========================
WS_URL = "ws://127.0.0.1:8080/ws/agent"

# =========================
# Runtime state
# =========================
STATE = {
    "enabled": True,
    "mode": "RUSH",
    "locked": False,
    "PREVIEW": True,
    "TUNER_ON": False,
}

# =========================
# Camera settings
# =========================
FRAME_W = 640
FRAME_H = 480
FLIP_MIRROR = True

CAP_BACKENDS = [
    cv2.CAP_DSHOW,
    cv2.CAP_MSMF,
    0,
]
CAM_INDEX_CANDIDATES = [0, 1, 2]

# =========================
# Tracking params
# =========================
# 너무 빡세면 빠르게 움직일 때 끊김. 일단 실사용 안정적으로.
MIN_AREA_RED  = 1800
MIN_AREA_BLUE = 1800
MAX_AREA = 160000

# 끊겨도 잠깐 유지
LOSS_GRACE_SEC = 0.22

# EMA: alpha가 클수록 "현재 값"을 더 믿음(=빠르게 따라감)
SMOOTH_ALPHA = 0.75

# 봉 모양 필터(회전 사각형 기준 긴변/짧은변)
ASPECT_MIN_STRICT = 2.0
ASPECT_MIN_RELAX  = 1.45

# morphology
KERNEL = np.ones((5, 5), np.uint8)

# 약한 블러(모션블러 상황에서 마스크 파편 줄이는 목적)
BLUR_K = 3

# =========================
# HSV ranges (initial)
# OpenCV HSV: H(0~179), S(0~255), V(0~255)
# =========================
BLUE_LO = np.array([95,  70,  60], dtype=np.uint8)
BLUE_HI = np.array([140, 255, 255], dtype=np.uint8)

# RED는 Hue wrap(170..179 U 0..10)
RED_LO = np.array([170, 120, 80], dtype=np.uint8)
RED_HI = np.array([10,  255, 255], dtype=np.uint8)

def now():
    return time.time()

def clamp01(v):
    return max(0.0, min(1.0, float(v)))

def ema(prev, cur, a):
    if prev is None:
        return cur
    return (1 - a) * prev + a * cur

def open_camera():
    for idx in CAM_INDEX_CANDIDATES:
        for be in CAP_BACKENDS:
            cap = cv2.VideoCapture(idx, be) if isinstance(be, int) else cv2.VideoCapture(idx)
            if not cap or not cap.isOpened():
                try:
                    cap.release()
                except:
                    pass
                continue

            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)

            # 가능하면 FPS 올려보기(카메라마다 무시될 수 있음)
            cap.set(cv2.CAP_PROP_FPS, 60)

            ok, frame = cap.read()
            if ok and frame is not None:
                print(f"[CAM] opened idx={idx}, backend={be}")
                return cap

            try:
                cap.release()
            except:
                pass

    raise RuntimeError("webcam open failed. 카메라 점유 앱 종료/권한/인덱스 확인 필요")

def build_mask(hsv, lo, hi):
    """
    Hue wrap 지원:
      - loH <= hiH: 일반 inRange
      - loH > hiH : [loH..179] U [0..hiH]
    """
    loH, loS, loV = int(lo[0]), int(lo[1]), int(lo[2])
    hiH, hiS, hiV = int(hi[0]), int(hi[1]), int(hi[2])

    if loH <= hiH:
        return cv2.inRange(
            hsv,
            np.array([loH, loS, loV], np.uint8),
            np.array([hiH, hiS, hiV], np.uint8),
        )

    m1 = cv2.inRange(hsv, np.array([loH, loS, loV], np.uint8), np.array([179, hiS, hiV], np.uint8))
    m2 = cv2.inRange(hsv, np.array([0,   loS, loV], np.uint8), np.array([hiH, hiS, hiV], np.uint8))
    return cv2.bitwise_or(m1, m2)

def contour_aspect_ratio(c):
    rect = cv2.minAreaRect(c)
    (w, h) = rect[1]
    w = float(w); h = float(h)
    short = max(1e-6, min(w, h))
    longv = max(w, h)
    return longv / short

def contour_topmost_point(c):
    """
    contour 점들 중 y가 가장 작은 점(최상단) -> 봉 끝점 추정에 유리
    반환: (x, y)
    """
    pts = c.reshape(-1, 2)
    i = np.argmin(pts[:, 1])
    return float(pts[i, 0]), float(pts[i, 1])

def find_marker_tip(hsv, lo, hi, min_area, aspect_min):
    mask = build_mask(hsv, lo, hi)

    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, KERNEL, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, KERNEL, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, mask

    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    for c in contours[:10]:
        area = float(cv2.contourArea(c))
        if area < float(min_area):
            continue
        if area > float(MAX_AREA):
            continue

        ar = contour_aspect_ratio(c)
        if ar < float(aspect_min):
            continue

        x, y, w, h = cv2.boundingRect(c)

        # 끝점(top-most) 사용
        tipx, tipy = contour_topmost_point(c)

        return (tipx, tipy, area, (x, y, w, h), ar), mask

    return None, mask

# =========================
# WS client
# =========================
_ws = None
_ws_connected = False

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
    try:
        data = json.loads(msg)
    except Exception:
        return
    typ = data.get("type")

    if typ == "ENABLE":
        STATE["enabled"] = True
        STATE["locked"] = False
        print("[PY] cmd ENABLE")

    elif typ == "DISABLE":
        STATE["enabled"] = False
        print("[PY] cmd DISABLE")

    elif typ == "SET_MODE":
        STATE["mode"] = str(data.get("mode", "RUSH")).upper()
        if STATE["mode"] == "RUSH":
            STATE["locked"] = False
        print("[PY] cmd SET_MODE ->", STATE["mode"])

    elif typ == "SET_PREVIEW":
        STATE["PREVIEW"] = bool(data.get("enabled", True))
        print("[PY] cmd SET_PREVIEW ->", STATE["PREVIEW"])

def send_status(ws, payload: dict):
    if ws is None or (not _ws_connected):
        return
    try:
        ws.send(json.dumps(payload))
    except Exception as e:
        print("[PY] send_status error:", e)

# =========================
# HSV tuner
# =========================
def ensure_tuner_window():
    cv2.namedWindow("HSV Tuner", cv2.WINDOW_NORMAL)
    def nothing(_): pass

    # RED
    cv2.createTrackbar("R_H_lo", "HSV Tuner", int(RED_LO[0]), 179, nothing)
    cv2.createTrackbar("R_S_lo", "HSV Tuner", int(RED_LO[1]), 255, nothing)
    cv2.createTrackbar("R_V_lo", "HSV Tuner", int(RED_LO[2]), 255, nothing)
    cv2.createTrackbar("R_H_hi", "HSV Tuner", int(RED_HI[0]), 179, nothing)
    cv2.createTrackbar("R_S_hi", "HSV Tuner", int(RED_HI[1]), 255, nothing)
    cv2.createTrackbar("R_V_hi", "HSV Tuner", int(RED_HI[2]), 255, nothing)

    # BLUE
    cv2.createTrackbar("B_H_lo", "HSV Tuner", int(BLUE_LO[0]), 179, nothing)
    cv2.createTrackbar("B_S_lo", "HSV Tuner", int(BLUE_LO[1]), 255, nothing)
    cv2.createTrackbar("B_V_lo", "HSV Tuner", int(BLUE_LO[2]), 255, nothing)
    cv2.createTrackbar("B_H_hi", "HSV Tuner", int(BLUE_HI[0]), 179, nothing)
    cv2.createTrackbar("B_S_hi", "HSV Tuner", int(BLUE_HI[1]), 255, nothing)
    cv2.createTrackbar("B_V_hi", "HSV Tuner", int(BLUE_HI[2]), 255, nothing)

def read_tuner_values():
    global RED_LO, RED_HI, BLUE_LO, BLUE_HI
    def g(name):
        return cv2.getTrackbarPos(name, "HSV Tuner")

    RED_LO  = np.array([g("R_H_lo"), g("R_S_lo"), g("R_V_lo")], dtype=np.uint8)
    RED_HI  = np.array([g("R_H_hi"), g("R_S_hi"), g("R_V_hi")], dtype=np.uint8)
    BLUE_LO = np.array([g("B_H_lo"), g("B_S_lo"), g("B_V_lo")], dtype=np.uint8)
    BLUE_HI = np.array([g("B_H_hi"), g("B_S_hi"), g("B_V_hi")], dtype=np.uint8)

def calibrate_from_center_roi(frame_bgr, target="RED"):
    global RED_LO, RED_HI, BLUE_LO, BLUE_HI

    h, w = frame_bgr.shape[:2]
    cx, cy = w // 2, h // 2
    r = 30
    x0, y0 = max(0, cx - r), max(0, cy - r)
    x1, y1 = min(w, cx + r), min(h, cy + r)

    roi = frame_bgr[y0:y1, x0:x1]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    H = hsv[:, :, 0].reshape(-1)
    S = hsv[:, :, 1].reshape(-1)
    V = hsv[:, :, 2].reshape(-1)

    m = (S > 60) & (V > 60)
    if np.count_nonzero(m) < 50:
        print("[CAL] ROI too gray/dark. 조명 밝게/대상을 더 가까이.")
        return

    h_med = int(np.median(H[m]))
    s_med = int(np.median(S[m]))
    v_med = int(np.median(V[m]))

    dH = 12
    loH = (h_med - dH) % 180
    hiH = (h_med + dH) % 180

    lo = np.array([loH, max(90, s_med - 80), max(60, v_med - 90)], dtype=np.uint8)
    hi = np.array([hiH, 255, 255], dtype=np.uint8)

    if target.upper() == "RED":
        RED_LO, RED_HI = lo, hi
        print("[CAL] RED  ->", RED_LO.tolist(), RED_HI.tolist(), "(wrap if lo>hi)")
    else:
        BLUE_LO, BLUE_HI = lo, hi
        print("[CAL] BLUE ->", BLUE_LO.tolist(), BLUE_HI.tolist(), "(wrap if lo>hi)")

def main():
    global _ws

    print("[PY] WS_URL:", WS_URL)
    cap = open_camera()

    def ws_loop():
        global _ws
        while True:
            try:
                ws = WebSocketApp(
                    WS_URL,
                    on_open=on_open,
                    on_close=on_close,
                    on_error=on_error,
                    on_message=on_message,
                )
                _ws = ws
                ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                print("[PY] ws_loop exception:", e)
            time.sleep(1.0)

    threading.Thread(target=ws_loop, daemon=True).start()

    # state for smoothing + grace
    red_last = None
    blue_last = None
    red_seen = 0.0
    blue_seen = 0.0

    fps = 0.0
    prev_t = now()

    preview_name = "Rush Color Agent (STICK) - ROBUST"
    window_open = False
    tuner_open = False

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            time.sleep(0.01)
            continue

        if FLIP_MIRROR:
            frame = cv2.flip(frame, 1)

        # 약한 블러로 마스크 파편/점노이즈 줄임
        if BLUR_K and BLUR_K >= 3:
            frame = cv2.GaussianBlur(frame, (BLUR_K, BLUR_K), 0)

        t = now()
        dt = max(1e-6, t - prev_t)
        prev_t = t
        fps = fps * 0.9 + (1.0 / dt) * 0.1

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # tuner
        if STATE["TUNER_ON"]:
            if not tuner_open:
                ensure_tuner_window()
                tuner_open = True
            read_tuner_values()
        else:
            if tuner_open:
                try:
                    cv2.destroyWindow("HSV Tuner")
                except:
                    pass
                tuner_open = False

        # 1차: strict
        red_info,  red_mask  = find_marker_tip(hsv, RED_LO,  RED_HI,  MIN_AREA_RED,  ASPECT_MIN_STRICT)
        blue_info, blue_mask = find_marker_tip(hsv, BLUE_LO, BLUE_HI, MIN_AREA_BLUE, ASPECT_MIN_STRICT)

        # 2차: relax(빠른 움직임/기울기에서 strict가 실패하는 경우 보완)
        if red_info is None:
            red_info, red_mask = find_marker_tip(hsv, RED_LO, RED_HI, int(MIN_AREA_RED * 0.6), ASPECT_MIN_RELAX)
        if blue_info is None:
            blue_info, blue_mask = find_marker_tip(hsv, BLUE_LO, BLUE_HI, int(MIN_AREA_BLUE * 0.6), ASPECT_MIN_RELAX)

        Hh, Ww = frame.shape[:2]

        # normalize + smoothing + grace
        red = None
        blue = None

        if red_info:
            tx, ty, area, bbox, ar = red_info
            nx, ny = clamp01(tx / Ww), clamp01(ty / Hh)
            red_seen = t
            red_last = (
                ema(red_last[0], nx, SMOOTH_ALPHA) if red_last else nx,
                ema(red_last[1], ny, SMOOTH_ALPHA) if red_last else ny,
            )
            red = {"nx": red_last[0], "ny": red_last[1], "bbox": bbox}
        else:
            if red_last and (t - red_seen) <= LOSS_GRACE_SEC:
                red = {"nx": red_last[0], "ny": red_last[1], "bbox": None}
            else:
                red_last = None

        if blue_info:
            tx, ty, area, bbox, ar = blue_info
            nx, ny = clamp01(tx / Ww), clamp01(ty / Hh)
            blue_seen = t
            blue_last = (
                ema(blue_last[0], nx, SMOOTH_ALPHA) if blue_last else nx,
                ema(blue_last[1], ny, SMOOTH_ALPHA) if blue_last else ny,
            )
            blue = {"nx": blue_last[0], "ny": blue_last[1], "bbox": bbox}
        else:
            if blue_last and (t - blue_seen) <= LOSS_GRACE_SEC:
                blue = {"nx": blue_last[0], "ny": blue_last[1], "bbox": None}
            else:
                blue_last = None

        mode_u = str(STATE["mode"]).upper()
        rush_ok = bool(STATE["enabled"] and mode_u == "RUSH")

        # =========================
        # 레인 고정: BLUE=Left, RED=Right
        # (프론트 RushScene이 BLUE->left로 찾는 로직이 있으니 맞춰줌)
        # =========================
        left_pack = None
        right_pack = None

        if blue:
            left_pack = {"gesture": "BLUE", "nx": blue["nx"], "ny": blue["ny"]}
        if red:
            right_pack = {"gesture": "RED", "nx": red["nx"], "ny": red["ny"]}

        payload = {
            "type": "STATUS",
            "enabled": bool(STATE["enabled"]),
            "mode": mode_u,
            "locked": bool(STATE["locked"]),
            "fps": float(fps),
            "gesture": "COLOR_STICK",
            "leftTracking": bool(rush_ok and left_pack is not None),
            "rightTracking": bool(rush_ok and right_pack is not None),
        }

        if left_pack:
            payload["leftPointerX"] = float(left_pack["nx"])
            payload["leftPointerY"] = float(left_pack["ny"])
            payload["leftGesture"] = left_pack["gesture"]
        if right_pack:
            payload["rightPointerX"] = float(right_pack["nx"])
            payload["rightPointerY"] = float(right_pack["ny"])
            payload["rightGesture"] = right_pack["gesture"]

        # fallback pointer(혹시 다른 UI에서 pointerX/Y만 쓰는 경우 대비)
        if right_pack:
            payload["pointerX"] = float(right_pack["nx"])
            payload["pointerY"] = float(right_pack["ny"])
            payload["isTracking"] = True
            payload["pointerGesture"] = right_pack["gesture"]
        elif left_pack:
            payload["pointerX"] = float(left_pack["nx"])
            payload["pointerY"] = float(left_pack["ny"])
            payload["isTracking"] = True
            payload["pointerGesture"] = left_pack["gesture"]
        else:
            payload["pointerX"] = None
            payload["pointerY"] = None
            payload["isTracking"] = False
            payload["pointerGesture"] = "NONE"

        send_status(_ws, payload)

        # PREVIEW
        if STATE["PREVIEW"]:
            if not window_open:
                cv2.namedWindow(preview_name, cv2.WINDOW_NORMAL)
                window_open = True

            cv2.putText(
                frame,
                f"mode={mode_u} enabled={STATE['enabled']} fps={fps:.1f}  RED={red is not None}  BLUE={blue is not None}",
                (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
            )
            cv2.putText(
                frame,
                f"ASPECT strict={ASPECT_MIN_STRICT:.2f}/relax={ASPECT_MIN_RELAX:.2f}  AREA={MIN_AREA_RED}/{MIN_AREA_BLUE}  alpha={SMOOTH_ALPHA:.2f}",
                (10, 48),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.52,
                (0, 255, 0),
                2,
            )

            if red_info and red_info[3]:
                x, y, bw, bh = red_info[3]
                cv2.rectangle(frame, (x, y), (x + bw, y + bh), (0, 0, 255), 2)
                cv2.putText(frame, "RED", (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                # tip point
                cv2.circle(frame, (int(red_info[0]), int(red_info[1])), 6, (0,0,255), -1)

            if blue_info and blue_info[3]:
                x, y, bw, bh = blue_info[3]
                cv2.rectangle(frame, (x, y), (x + bw, y + bh), (255, 0, 0), 2)
                cv2.putText(frame, "BLUE", (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
                cv2.circle(frame, (int(blue_info[0]), int(blue_info[1])), 6, (255,0,0), -1)

            cv2.imshow(preview_name, frame)

            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                break
            elif key in (ord("e"), ord("E")):
                STATE["enabled"] = not STATE["enabled"]
                print("[KEY] enabled:", STATE["enabled"])
            elif key in (ord("p"), ord("P")):
                STATE["PREVIEW"] = not STATE["PREVIEW"]
                print("[KEY] PREVIEW:", STATE["PREVIEW"])
            elif key in (ord("t"), ord("T")):
                STATE["TUNER_ON"] = not STATE["TUNER_ON"]
                print("[KEY] TUNER_ON:", STATE["TUNER_ON"])
            elif key in (ord("d"), ord("D")):
                print("[HSV] RED_LO/HI :", RED_LO.tolist(), RED_HI.tolist(), "(wrap if lo>hi)")
                print("[HSV] BLUE_LO/HI:", BLUE_LO.tolist(), BLUE_HI.tolist(), "(wrap if lo>hi)")
            elif key == ord("1"):
                calibrate_from_center_roi(frame, "RED")
            elif key == ord("2"):
                calibrate_from_center_roi(frame, "BLUE")

        else:
            if window_open:
                try:
                    cv2.destroyWindow(preview_name)
                except:
                    pass
                window_open = False
            time.sleep(0.005)

    try:
        cap.release()
    except:
        pass
    try:
        cv2.destroyAllWindows()
    except:
        pass

if __name__ == "__main__":
    main()
