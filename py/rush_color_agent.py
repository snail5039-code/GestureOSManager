"""
rush_color_agent.py
- OpenCV HSV 기반 컬러 트래킹으로 Rush 입력(left/rightPointerX/Y, gesture) 전송
- Hue wrap 지원(H_lo > H_hi면 [lo..179] U [0..hi])

Keys (preview window focus):
  ESC : quit
  E   : enabled toggle
  P   : PREVIEW toggle
  T   : HSV tuner toggle
  D   : print HSV ranges
  1   : calibrate PINK from center ROI
  2   : calibrate YELLOW from center ROI
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
# Runtime state (no global assignment issues)
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
    cv2.CAP_DSHOW,  # Windows 안정
    cv2.CAP_MSMF,
    0,
]
CAM_INDEX_CANDIDATES = [0, 1, 2]

# =========================
# Tracking params
# =========================
MIN_AREA = 1200
MAX_AREA = 45000          # 얼굴 같은 큰 덩어리 방지용(상황에 따라 조절)
LOSS_GRACE_SEC = 0.25
SMOOTH_ALPHA = 0.35

KERNEL = np.ones((5, 5), np.uint8)

# =========================
# HSV ranges (initial)
# OpenCV HSV: H(0~179), S(0~255), V(0~255)
# =========================
# 노랑(대체로 잘 잡힘)
YEL_LO = np.array([18, 80, 140], dtype=np.uint8)
YEL_HI = np.array([40, 255, 255], dtype=np.uint8)

# 핑크/빨강 계열은 wrap 가능성이 큼
# H_lo > H_hi 로 두 구간 OR 처리되게 "wrap 기본값"으로 둠
PINK_LO = np.array([170, 140, 120], dtype=np.uint8)  # H=170..179
PINK_HI = np.array([10, 255, 255], dtype=np.uint8)   # H=0..10  (wrap)

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
        return cv2.inRange(hsv, np.array([loH, loS, loV], np.uint8), np.array([hiH, hiS, hiV], np.uint8))

    # wrap
    m1 = cv2.inRange(hsv, np.array([loH, loS, loV], np.uint8), np.array([179, hiS, hiV], np.uint8))
    m2 = cv2.inRange(hsv, np.array([0,   loS, loV], np.uint8), np.array([hiH, hiS, hiV], np.uint8))
    return cv2.bitwise_or(m1, m2)

def find_marker_center(hsv, lo, hi):
    mask = build_mask(hsv, lo, hi)

    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, KERNEL, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, KERNEL, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, mask

    # 가장 큰 컨투어 후보들 중 area 필터 적용
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    picked = None
    for c in contours[:5]:
        area = float(cv2.contourArea(c))
        if area < MIN_AREA:
            continue
        if area > MAX_AREA:
            continue
        M = cv2.moments(c)
        if M["m00"] <= 1e-6:
            continue
        cx = float(M["m10"] / M["m00"])
        cy = float(M["m01"] / M["m00"])
        x, y, w, h = cv2.boundingRect(c)
        picked = (cx, cy, area, (x, y, w, h))
        break

    return picked, mask

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
    # Spring -> Python command (optional)
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

    # PINK
    cv2.createTrackbar("P_H_lo", "HSV Tuner", int(PINK_LO[0]), 179, nothing)
    cv2.createTrackbar("P_S_lo", "HSV Tuner", int(PINK_LO[1]), 255, nothing)
    cv2.createTrackbar("P_V_lo", "HSV Tuner", int(PINK_LO[2]), 255, nothing)
    cv2.createTrackbar("P_H_hi", "HSV Tuner", int(PINK_HI[0]), 179, nothing)
    cv2.createTrackbar("P_S_hi", "HSV Tuner", int(PINK_HI[1]), 255, nothing)
    cv2.createTrackbar("P_V_hi", "HSV Tuner", int(PINK_HI[2]), 255, nothing)

    # YELLOW
    cv2.createTrackbar("Y_H_lo", "HSV Tuner", int(YEL_LO[0]), 179, nothing)
    cv2.createTrackbar("Y_S_lo", "HSV Tuner", int(YEL_LO[1]), 255, nothing)
    cv2.createTrackbar("Y_V_lo", "HSV Tuner", int(YEL_LO[2]), 255, nothing)
    cv2.createTrackbar("Y_H_hi", "HSV Tuner", int(YEL_HI[0]), 179, nothing)
    cv2.createTrackbar("Y_S_hi", "HSV Tuner", int(YEL_HI[1]), 255, nothing)
    cv2.createTrackbar("Y_V_hi", "HSV Tuner", int(YEL_HI[2]), 255, nothing)

def read_tuner_values():
    global PINK_LO, PINK_HI, YEL_LO, YEL_HI

    def g(name):
        return cv2.getTrackbarPos(name, "HSV Tuner")

    PINK_LO = np.array([g("P_H_lo"), g("P_S_lo"), g("P_V_lo")], dtype=np.uint8)
    PINK_HI = np.array([g("P_H_hi"), g("P_S_hi"), g("P_V_hi")], dtype=np.uint8)
    YEL_LO  = np.array([g("Y_H_lo"), g("Y_S_lo"), g("Y_V_lo")], dtype=np.uint8)
    YEL_HI  = np.array([g("Y_H_hi"), g("Y_S_hi"), g("Y_V_hi")], dtype=np.uint8)

def calibrate_from_center_roi(frame_bgr, target="YELLOW"):
    """
    화면 중앙 ROI(60x60) 픽셀의 HSV 중앙값 기반으로 lo/hi 자동 세팅.
    """
    global PINK_LO, PINK_HI, YEL_LO, YEL_HI

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

    # 너무 어두운/무채색 픽셀 제외
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

    lo = np.array([loH, max(80, s_med - 80), max(80, v_med - 80)], dtype=np.uint8)
    hi = np.array([hiH, 255, 255], dtype=np.uint8)

    if target == "YELLOW":
        YEL_LO, YEL_HI = lo, hi
        print("[CAL] YELLOW ->", YEL_LO.tolist(), YEL_HI.tolist(), "(H wrap if lo>hi)")
    else:
        PINK_LO, PINK_HI = lo, hi
        print("[CAL] PINK ->", PINK_LO.tolist(), PINK_HI.tolist(), "(H wrap if lo>hi)")

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

    pink_last = None
    yel_last = None
    pink_seen = 0.0
    yel_seen = 0.0

    fps = 0.0
    prev_t = now()

    preview_name = "Rush Color Agent"
    window_open = False
    tuner_open = False

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            time.sleep(0.01)
            continue

        if FLIP_MIRROR:
            frame = cv2.flip(frame, 1)

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

        pink_info, pink_mask = find_marker_center(hsv, PINK_LO, PINK_HI)
        yel_info,  yel_mask  = find_marker_center(hsv, YEL_LO,  YEL_HI)

        Hh, Ww = frame.shape[:2]

        # normalize + smoothing + grace
        pink = None
        yel = None

        if pink_info:
            cx, cy, area, bbox = pink_info
            nx, ny = clamp01(cx / Ww), clamp01(cy / Hh)
            pink_seen = t
            pink_last = (
                ema(pink_last[0], nx, SMOOTH_ALPHA) if pink_last else nx,
                ema(pink_last[1], ny, SMOOTH_ALPHA) if pink_last else ny,
            )
            pink = {"nx": pink_last[0], "ny": pink_last[1], "bbox": bbox}
        else:
            if pink_last and (t - pink_seen) <= LOSS_GRACE_SEC:
                pink = {"nx": pink_last[0], "ny": pink_last[1], "bbox": None}
            else:
                pink_last = None

        if yel_info:
            cx, cy, area, bbox = yel_info
            nx, ny = clamp01(cx / Ww), clamp01(cy / Hh)
            yel_seen = t
            yel_last = (
                ema(yel_last[0], nx, SMOOTH_ALPHA) if yel_last else nx,
                ema(yel_last[1], ny, SMOOTH_ALPHA) if yel_last else ny,
            )
            yel = {"nx": yel_last[0], "ny": yel_last[1], "bbox": bbox}
        else:
            if yel_last and (t - yel_seen) <= LOSS_GRACE_SEC:
                yel = {"nx": yel_last[0], "ny": yel_last[1], "bbox": None}
            else:
                yel_last = None

        # left/right assignment
        left_pack = None
        right_pack = None

        if pink and yel:
            pairs = [("PINK", pink["nx"], pink["ny"]), ("YELLOW", yel["nx"], yel["ny"])]
            pairs.sort(key=lambda x: x[1])  # x 기준 left/right
            left_pack  = {"gesture": pairs[0][0], "nx": pairs[0][1], "ny": pairs[0][2]}
            right_pack = {"gesture": pairs[1][0], "nx": pairs[1][1], "ny": pairs[1][2]}
        else:
            # 단일만 있으면 x 기준으로 lane 배치
            single = None
            if yel:
                single = {"gesture": "YELLOW", "nx": yel["nx"], "ny": yel["ny"]}
            elif pink:
                single = {"gesture": "PINK", "nx": pink["nx"], "ny": pink["ny"]}

            if single:
                if single["nx"] < 0.5:
                    left_pack = single
                else:
                    right_pack = single

        mode_u = str(STATE["mode"]).upper()

        payload = {
            "type": "STATUS",
            "enabled": bool(STATE["enabled"]),
            "mode": mode_u,
            "locked": bool(STATE["locked"]),
            "fps": float(fps),
            "gesture": "COLOR",
            "leftTracking": bool(STATE["enabled"] and mode_u == "RUSH" and left_pack is not None),
            "rightTracking": bool(STATE["enabled"] and mode_u == "RUSH" and right_pack is not None),
        }

        if left_pack:
            payload["leftPointerX"] = float(left_pack["nx"])
            payload["leftPointerY"] = float(left_pack["ny"])
            payload["leftGesture"] = left_pack["gesture"]
        if right_pack:
            payload["rightPointerX"] = float(right_pack["nx"])
            payload["rightPointerY"] = float(right_pack["ny"])
            payload["rightGesture"] = right_pack["gesture"]

        # single fallback
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
                f"mode={mode_u} enabled={STATE['enabled']} fps={fps:.1f}  PINK={pink is not None}  YEL={yel is not None}",
                (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
            )

            # draw boxes from raw detections
            if pink_info and pink_info[3]:
                x, y, bw, bh = pink_info[3]
                cv2.rectangle(frame, (x, y), (x + bw, y + bh), (255, 0, 255), 2)
                cv2.putText(frame, "PINK", (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 255), 2)

            if yel_info and yel_info[3]:
                x, y, bw, bh = yel_info[3]
                cv2.rectangle(frame, (x, y), (x + bw, y + bh), (0, 255, 255), 2)
                cv2.putText(frame, "YELLOW", (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

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
                print("[HSV] PINK_LO/HI:", PINK_LO.tolist(), PINK_HI.tolist(), "(wrap if H_lo > H_hi)")
                print("[HSV] YEL_LO/HI :", YEL_LO.tolist(),  YEL_HI.tolist(),  "(wrap if H_lo > H_hi)")
            elif key == ord("1"):
                calibrate_from_center_roi(frame, "PINK")
            elif key == ord("2"):
                calibrate_from_center_roi(frame, "YELLOW")
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
