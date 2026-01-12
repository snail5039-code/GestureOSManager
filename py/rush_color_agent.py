"""
rush_color_agent.py (STICK COLOR VERSION - ROBUST)
- OpenCV HSV 기반 "봉 바디 색" 트래킹 (RED / BLUE)
- 빠른 상하 이동에서 검출 끊김 개선:
  1) 카메라 MJPG/FPS/노출(가능 시) 고정
  2) 검출 실패해도 grace 동안 "속도 기반 예측"으로 좌표 계속 내보냄 (슬래시 끊김 방지)
  3) 이전 bbox 주변 ROI에서는 느슨한 임계치+완화된 모양필터로 재탐색(재획득 강화)
  4) 트래킹 중에는 MIN_AREA/ASPECT 조건을 완화

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
TARGET_FPS = 60  # 가능하면 60, 안 되면 드라이버가 무시할 수 있음
FLIP_MIRROR = True

CAP_BACKENDS = [
    cv2.CAP_DSHOW,
    cv2.CAP_MSMF,
    0,
]
CAM_INDEX_CANDIDATES = [0, 1, 2]

# =========================
# Tracking params (tune here)
# =========================
# "처음 재획득(전체 프레임)"에서는 좀 엄격
MIN_AREA_RED_STRICT = 3500
MIN_AREA_BLUE_STRICT = 3500

# "트래킹 유지/ROI"에서는 완화 (빠르게 움직일 때 끊기는 주범 해결)
MIN_AREA_RED_RELAX = 1400
MIN_AREA_BLUE_RELAX = 1400

MAX_AREA = 150000

# 봉 모양 필터(회전사각형 긴변/짧은변 비율)
ASPECT_MIN_STRICT = 2.2
ASPECT_MIN_RELAX = 1.55  # 빠르게 움직이면 블러로 두께가 퍼져서 비율이 내려감

# 검출 잠깐 끊겨도 유지하는 시간 (그리고 이 동안은 예측 좌표 내보냄)
LOSS_GRACE_SEC = 0.25

# 위치 EMA (0~1). 클수록 즉각 반응(덜 부드러움, 더 빠름)
# 슬래시를 살리려면 너무 낮게(0.35 같은) 잡지 말 것
SMOOTH_ALPHA = 0.75

# ROI 확장 비율 (이전 bbox 주변을 얼마나 넓게 재탐색할지)
ROI_EXPAND = 1.8

# ROI에서 임계치를 느슨하게 할 때 S/V를 얼마나 낮출지
LOOSEN_S = 40
LOOSEN_V = 60

# Morphology kernel (마스크 끊김 연결)
KERNEL = np.ones((5, 5), np.uint8)

# =========================
# HSV ranges (initial)
# OpenCV HSV: H(0~179), S(0~255), V(0~255)
# =========================
BLUE_LO = np.array([95,  60,  40], dtype=np.uint8)
BLUE_HI = np.array([140, 255, 255], dtype=np.uint8)

# RED: wrap(170..179 U 0..10)
RED_LO = np.array([170, 110, 70], dtype=np.uint8)
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
    """
    - MJPG + FPS + (가능하면) 오토노출 끄기
    - 이게 되면 "내려갈 때 어두워져서 색이 죽는 문제"가 확 줄어듦
    """
    for idx in CAM_INDEX_CANDIDATES:
        for be in CAP_BACKENDS:
            cap = cv2.VideoCapture(idx, be) if isinstance(be, int) else cv2.VideoCapture(idx)
            if not cap or not cap.isOpened():
                try:
                    cap.release()
                except Exception:
                    pass
                continue

            # 버퍼 최소
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            # MJPG: 지연/프레임 안정화에 도움 (가능하면)
            try:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            except Exception:
                pass

            cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_W)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_H)
            cap.set(cv2.CAP_PROP_FPS, TARGET_FPS)

            # 오토노출 끄기/노출 고정 (드라이버에 따라 무시될 수 있음)
            # DSHOW 계열: AUTO_EXPOSURE 0.25가 "manual"로 동작하는 경우가 많음
            try:
                cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
                cap.set(cv2.CAP_PROP_EXPOSURE, -6)  # -4~-8 사이로 튜닝 가능
            except Exception:
                pass

            ok, frame = cap.read()
            if ok and frame is not None:
                print(f"[CAM] opened idx={idx}, backend={be}")
                return cap

            try:
                cap.release()
            except Exception:
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

    # wrap
    m1 = cv2.inRange(hsv, np.array([loH, loS, loV], np.uint8), np.array([179, hiS, hiV], np.uint8))
    m2 = cv2.inRange(hsv, np.array([0,   loS, loV], np.uint8), np.array([hiH, hiS, hiV], np.uint8))
    return cv2.bitwise_or(m1, m2)


def contour_aspect_ratio(c):
    rect = cv2.minAreaRect(c)  # ((cx,cy),(w,h),angle)
    (w, h) = rect[1]
    w = float(w)
    h = float(h)
    short = max(1e-6, min(w, h))
    longv = max(w, h)
    return longv / short


def loosen_lo(lo, dS=40, dV=60):
    """
    ROI 재탐색에서만 S/V 문턱을 낮춰서
    어두워지거나 모션블러로 색이 약해져도 잡히게 한다.
    """
    loH, loS, loV = int(lo[0]), int(lo[1]), int(lo[2])
    return np.array([loH, max(0, loS - dS), max(0, loV - dV)], dtype=np.uint8)


def find_marker_center(hsv_full, lo, hi, min_area, aspect_min, roi=None):
    """
    roi: (x0,y0,x1,y1) in full-frame coords. None이면 전체 프레임.
    반환:
      picked = (tipx, tipy, area, bbox(x,y,w,h), ar)
      mask (roi 기준 마스크) -> 디버그용
    """
    if roi is not None:
        x0, y0, x1, y1 = roi
        hsv = hsv_full[y0:y1, x0:x1]
    else:
        x0, y0 = 0, 0
        hsv = hsv_full

    mask = build_mask(hsv, lo, hi)

    # 마스크 끊김을 연결(빠른 모션 블러 대응)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, KERNEL, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, KERNEL, iterations=2)
    mask = cv2.dilate(mask, KERNEL, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, mask

    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    picked = None
    for c in contours[:10]:
        area = float(cv2.contourArea(c))
        if area < float(min_area):
            continue
        if area > float(MAX_AREA):
            continue

        ar = contour_aspect_ratio(c)
        if ar < float(aspect_min):
            continue

        M = cv2.moments(c)
        if M["m00"] <= 1e-6:
            continue

        # bbox (roi 좌표)
        rx, ry, rw, rh = cv2.boundingRect(c)

        # 봉 "윗끝" 근처를 tip으로 사용(너 코드 그대로 유지)
        tipx = rx + rw * 0.5
        tipy = ry + rh * 0.15

        # full-frame 좌표로 환산
        fx = float(tipx + x0)
        fy = float(tipy + y0)
        bx = int(rx + x0)
        by = int(ry + y0)

        picked = (fx, fy, area, (bx, by, int(rw), int(rh)), float(ar))
        break

    return picked, mask


class TrackState:
    """
    - detect 성공: pos 갱신 + 속도 추정
    - detect 실패: grace 동안 predict()로 좌표를 계속 만들어낸다 (슬래시 끊김 방지 핵심)
    """
    def __init__(self):
        self.pos = None        # (nx, ny)
        self.vel = (0.0, 0.0)  # (vnx, vny) per second
        self.last_t = None
        self.seen_t = 0.0
        self.bbox = None
        self.predicted = False

    def update_detect(self, nx, ny, bbox, t):
        self.predicted = False

        if self.pos is not None and self.last_t is not None:
            dt = max(1e-4, t - self.last_t)
            vx = (nx - self.pos[0]) / dt
            vy = (ny - self.pos[1]) / dt
            # 폭주 방지 (grace 예측용)
            vx = float(np.clip(vx, -3.0, 3.0))
            vy = float(np.clip(vy, -3.0, 3.0))
            self.vel = (vx, vy)

        self.pos = (nx, ny)
        self.bbox = bbox
        self.last_t = t
        self.seen_t = t

    def predict(self, t):
        if self.pos is None or self.last_t is None:
            return None
        dt = max(0.0, t - self.last_t)
        px = self.pos[0] + self.vel[0] * dt
        py = self.pos[1] + self.vel[1] * dt
        px = clamp01(px)
        py = clamp01(py)

        self.pos = (px, py)
        self.last_t = t
        self.predicted = True
        return (px, py)

    def is_alive(self, t, grace_sec):
        return self.pos is not None and (t - self.seen_t) <= grace_sec


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

    def nothing(_):
        pass

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

    RED_LO = np.array([g("R_H_lo"), g("R_S_lo"), g("R_V_lo")], dtype=np.uint8)
    RED_HI = np.array([g("R_H_hi"), g("R_S_hi"), g("R_V_hi")], dtype=np.uint8)
    BLUE_LO = np.array([g("B_H_lo"), g("B_S_lo"), g("B_V_lo")], dtype=np.uint8)
    BLUE_HI = np.array([g("B_H_hi"), g("B_S_hi"), g("B_V_hi")], dtype=np.uint8)


def calibrate_from_center_roi(frame_bgr, target="RED"):
    """
    화면 중앙 ROI(60x60)의 HSV 중앙값 기반으로 lo/hi 자동 세팅.
    - RED는 wrap 가능
    """
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


def bbox_to_roi(bbox, W, H, expand=1.8):
    """
    bbox: (x,y,w,h) in full frame
    expand: 얼마나 확장할지
    """
    if not bbox:
        return None
    x, y, w, h = bbox
    cx = x + w * 0.5
    cy = y + h * 0.5
    nw = w * expand
    nh = h * expand
    x0 = int(max(0, cx - nw * 0.5))
    y0 = int(max(0, cy - nh * 0.5))
    x1 = int(min(W, cx + nw * 0.5))
    y1 = int(min(H, cy + nh * 0.5))
    if x1 - x0 < 10 or y1 - y0 < 10:
        return None
    return (x0, y0, x1, y1)


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

    redS = TrackState()
    blueS = TrackState()

    fps = 0.0
    prev_t = now()

    preview_name = "Rush Color Agent (STICK) - ROBUST"
    window_open = False
    tuner_open = False

    # 디버그용 마스크(필요하면 켜서 확인)
    show_masks = False

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            time.sleep(0.005)
            continue

        if FLIP_MIRROR:
            frame = cv2.flip(frame, 1)

        t = now()
        dt = max(1e-6, t - prev_t)
        prev_t = t
        fps = fps * 0.9 + (1.0 / dt) * 0.1

        Hh, Ww = frame.shape[:2]
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
                except Exception:
                    pass
                tuner_open = False

        # =========
        # Detect helper: ROI -> relaxed -> strict fallback
        # =========
        def detect_color(track: TrackState, lo, hi, min_strict, min_relax):
            # 1) ROI 주변 (트래킹 중이면) : 느슨한 lo + 완화 조건
            roi = bbox_to_roi(track.bbox, Ww, Hh, expand=ROI_EXPAND) if track.bbox else None

            picked = None
            mask_used = None

            if roi is not None:
                lo2 = loosen_lo(lo, dS=LOOSEN_S, dV=LOOSEN_V)
                picked, mask_used = find_marker_center(
                    hsv, lo2, hi,
                    min_area=min_relax,
                    aspect_min=ASPECT_MIN_RELAX,
                    roi=roi
                )

            # 2) ROI에서 못 찾으면 전체 프레임: (트래킹 중이면 조건 조금 완화, 아니면 엄격)
            if picked is None:
                alive = track.is_alive(t, LOSS_GRACE_SEC)
                min_area = min_relax if alive else min_strict
                aspect_min = ASPECT_MIN_RELAX if alive else ASPECT_MIN_STRICT
                picked, mask_used = find_marker_center(
                    hsv, lo, hi,
                    min_area=min_area,
                    aspect_min=aspect_min,
                    roi=None
                )

            return picked, mask_used

        red_info, red_mask = detect_color(
            redS, RED_LO, RED_HI, MIN_AREA_RED_STRICT, MIN_AREA_RED_RELAX
        )
        blue_info, blue_mask = detect_color(
            blueS, BLUE_LO, BLUE_HI, MIN_AREA_BLUE_STRICT, MIN_AREA_BLUE_RELAX
        )

        # =========
        # Update tracks (detect / predict)
        # =========
        def apply_track(track: TrackState, info):
            if info is not None:
                tipx, tipy, area, bbox, ar = info
                nx = clamp01(tipx / Ww)
                ny = clamp01(tipy / Hh)

                # EMA (너무 부드럽게 하면 속도가 죽어서 슬래시가 안 나옴)
                if track.pos is not None:
                    nx = ema(track.pos[0], nx, SMOOTH_ALPHA)
                    ny = ema(track.pos[1], ny, SMOOTH_ALPHA)

                track.update_detect(nx, ny, bbox, t)
                return True
            else:
                # detect 실패면 grace 동안 예측 좌표를 계속 갱신
                if track.is_alive(t, LOSS_GRACE_SEC):
                    track.predict(t)
                    track.bbox = None  # ROI 근거 bbox가 없으니 제거
                    return True
                else:
                    # 완전 소실
                    track.pos = None
                    track.bbox = None
                    track.last_t = None
                    track.seen_t = 0.0
                    track.vel = (0.0, 0.0)
                    track.predicted = False
                    return False

        red_alive = apply_track(redS, red_info)
        blue_alive = apply_track(blueS, blue_info)

        # =========
        # left/right assignment (x 기준) + payload 구성
        # =========
        # 여기서는 "RED/BLUE"를 gesture로 넣고,
        # 프론트에서는 BLUE->left, RED->right로 고정하려는 로직이 있었지.
        # 다만 막대가 서로 위치 바뀌면 혼란이 생길 수 있으니,
        # 지금은 "x 기준 left/right"로 유지하되, 각 막대의 gesture는 유지한다.
        left_pack = None
        right_pack = None

        if redS.pos is not None and blueS.pos is not None:
            pairs = [("RED", redS.pos[0], redS.pos[1]), ("BLUE", blueS.pos[0], blueS.pos[1])]
            pairs.sort(key=lambda x: x[1])
            left_pack = {"gesture": pairs[0][0], "nx": pairs[0][1], "ny": pairs[0][2]}
            right_pack = {"gesture": pairs[1][0], "nx": pairs[1][1], "ny": pairs[1][2]}
        else:
            single = None
            if redS.pos is not None:
                single = {"gesture": "RED", "nx": redS.pos[0], "ny": redS.pos[1]}
            elif blueS.pos is not None:
                single = {"gesture": "BLUE", "nx": blueS.pos[0], "ny": blueS.pos[1]}

            if single:
                if single["nx"] < 0.5:
                    left_pack = single
                else:
                    right_pack = single

        mode_u = str(STATE["mode"]).upper()
        enabled = bool(STATE["enabled"]) and (mode_u == "RUSH")

        payload = {
            "type": "STATUS",
            "enabled": bool(STATE["enabled"]),
            "mode": mode_u,
            "locked": bool(STATE["locked"]),
            "fps": float(fps),
            "gesture": "COLOR_STICK",
            "leftTracking": bool(enabled and left_pack is not None),
            "rightTracking": bool(enabled and right_pack is not None),
        }

        if left_pack:
            payload["leftPointerX"] = float(left_pack["nx"])
            payload["leftPointerY"] = float(left_pack["ny"])
            payload["leftGesture"] = left_pack["gesture"]
        if right_pack:
            payload["rightPointerX"] = float(right_pack["nx"])
            payload["rightPointerY"] = float(right_pack["ny"])
            payload["rightGesture"] = right_pack["gesture"]

        # fallback pointer: 하나만 있어도 pointerX/Y는 유지
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

        # =========
        # PREVIEW UI
        # =========
        if STATE["PREVIEW"]:
            if not window_open:
                cv2.namedWindow(preview_name, cv2.WINDOW_NORMAL)
                window_open = True

            # 상태 텍스트
            cv2.putText(
                frame,
                f"mode={mode_u} enabled={STATE['enabled']} fps={fps:.1f}  RED={redS.pos is not None}  BLUE={blueS.pos is not None}",
                (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
            )
            cv2.putText(
                frame,
                f"ASPECT strict={ASPECT_MIN_STRICT:.2f}/relax={ASPECT_MIN_RELAX:.2f}  AREA strict={MIN_AREA_RED_STRICT}/{MIN_AREA_RED_RELAX}",
                (10, 48),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 255, 0),
                2,
            )

            # bbox 그리기 (detect 성공시에만 bbox가 있음)
            if red_info and red_info[3]:
                x, y, bw, bh = red_info[3]
                cv2.rectangle(frame, (x, y), (x + bw, y + bh), (0, 0, 255), 2)
                cv2.putText(frame, "RED", (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

            if blue_info and blue_info[3]:
                x, y, bw, bh = blue_info[3]
                cv2.rectangle(frame, (x, y), (x + bw, y + bh), (255, 0, 0), 2)
                cv2.putText(frame, "BLUE", (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)

            # 예측 중이면 표시
            if redS.predicted:
                cv2.putText(frame, "RED PRED", (10, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
            if blueS.predicted:
                cv2.putText(frame, "BLUE PRED", (120, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 0, 0), 2)

            cv2.imshow(preview_name, frame)

            if show_masks:
                cv2.imshow("mask_red", red_mask)
                cv2.imshow("mask_blue", blue_mask)

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
            elif key in (ord("m"), ord("M")):
                show_masks = not show_masks
                print("[KEY] show_masks:", show_masks)
        else:
            if window_open:
                try:
                    cv2.destroyWindow(preview_name)
                except Exception:
                    pass
                window_open = False
            time.sleep(0.003)

    try:
        cap.release()
    except Exception:
        pass
    try:
        cv2.destroyAllWindows()
    except Exception:
        pass


if __name__ == "__main__":
    main()
