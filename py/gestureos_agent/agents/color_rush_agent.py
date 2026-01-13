import json
import time
import threading
import cv2
import numpy as np
from websocket import WebSocketApp

from ..config import AgentConfig
from ..timeutil import now
from ..ws_client import WSClient

class ColorRushAgent:
    """
    HSV-based stick tracking (RED/BLUE) for RUSH.
    - Sends STATUS to the same WS endpoint as hands agent.
    - Keys (preview window focus):
        ESC : quit
        E   : enabled toggle
        P   : PREVIEW toggle
        T   : HSV tuner toggle (trackbar)
        D   : print HSV ranges
        1   : calibrate RED from center ROI
        2   : calibrate BLUE from center ROI
    """
    FRAME_W = 640
    FRAME_H = 480
    FLIP_MIRROR = True

    MIN_AREA_RED  = 1800
    MIN_AREA_BLUE = 1800
    MAX_AREA = 160000

    LOSS_GRACE_SEC = 0.22
    SMOOTH_ALPHA = 0.75

    ASPECT_MIN_STRICT = 2.0
    ASPECT_MIN_RELAX  = 1.45

    KERNEL = None
    BLUR_K = 3

    BLUE_LO = np.array([95,  70,  60], dtype=np.uint8)
    BLUE_HI = np.array([140, 255, 255], dtype=np.uint8)

    RED_LO = np.array([170, 120, 80], dtype=np.uint8)
    RED_HI = np.array([10,  255, 255], dtype=np.uint8)

    def __init__(self, cfg: AgentConfig):
        self.cfg = cfg

        self.enabled = True if cfg.start_enabled else True  # color agent is typically on by default
        self.mode = "RUSH"
        self.locked = False
        self.preview = (not cfg.headless)

        self.tuner_on = False

        self.kernel = np.ones((5, 5), np.uint8)
        self.red_last = None
        self.blue_last = None
        self.red_seen = 0.0
        self.blue_seen = 0.0

        self.ws = WSClient(cfg.ws_url, self._on_command, enabled=(not cfg.no_ws))

    # -------- WS incoming commands --------
    def _on_command(self, data: dict):
        typ = data.get("type")
        if typ == "ENABLE":
            self.enabled = True
            self.locked = False
            print("[PY] cmd ENABLE")
        elif typ == "DISABLE":
            self.enabled = False
            print("[PY] cmd DISABLE")
        elif typ == "SET_MODE":
            self.mode = str(data.get("mode", "RUSH")).upper()
            if self.mode == "RUSH":
                self.locked = False
            print("[PY] cmd SET_MODE ->", self.mode)
        elif typ == "SET_PREVIEW":
            self.preview = bool(data.get("enabled", True))
            print("[PY] cmd SET_PREVIEW ->", self.preview)

    # -------- camera --------
    def open_camera(self):
        backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, 0]
        cam_idxs = [0, 1, 2]
        for idx in cam_idxs:
            for be in backends:
                try:
                    cap = cv2.VideoCapture(idx, be) if isinstance(be, int) else cv2.VideoCapture(idx)
                except Exception:
                    cap = cv2.VideoCapture(idx)
                if not cap or not cap.isOpened():
                    try:
                        cap.release()
                    except Exception:
                        pass
                    continue

                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.FRAME_W)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.FRAME_H)
                cap.set(cv2.CAP_PROP_FPS, 60)

                ok, frame = cap.read()
                if ok and frame is not None:
                    print(f"[CAM] opened idx={idx}, backend={be}")
                    return cap

                try:
                    cap.release()
                except Exception:
                    pass

        raise RuntimeError("webcam open failed. 카메라 점유 앱 종료/권한/인덱스 확인 필요")

    # -------- tracking helpers --------
    @staticmethod
    def clamp01(v):
        return max(0.0, min(1.0, float(v)))

    @staticmethod
    def ema(prev, cur, a):
        if prev is None:
            return cur
        return (1 - a) * prev + a * cur

    def build_mask(self, hsv, lo, hi):
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

    @staticmethod
    def contour_aspect_ratio(c):
        rect = cv2.minAreaRect(c)
        (w, h) = rect[1]
        w = float(w); h = float(h)
        short = max(1e-6, min(w, h))
        longv = max(w, h)
        return longv / short

    @staticmethod
    def contour_topmost_point(c):
        pts = c.reshape(-1, 2)
        i = np.argmin(pts[:, 1])
        return float(pts[i, 0]), float(pts[i, 1])

    def find_marker_tip(self, hsv, lo, hi, min_area, aspect_min):
        mask = self.build_mask(hsv, lo, hi)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self.kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None, mask

        contours = sorted(contours, key=cv2.contourArea, reverse=True)

        for c in contours[:10]:
            area = float(cv2.contourArea(c))
            if area < float(min_area):
                continue
            if area > float(self.MAX_AREA):
                continue

            ar = self.contour_aspect_ratio(c)
            if ar < float(aspect_min):
                continue

            x, y, w, h = cv2.boundingRect(c)
            tipx, tipy = self.contour_topmost_point(c)
            return (tipx, tipy, area, (x, y, w, h), ar), mask

        return None, mask

    # -------- tuner --------
    def ensure_tuner_window(self):
        cv2.namedWindow("HSV Tuner", cv2.WINDOW_NORMAL)

        def nothing(_): pass

        # RED
        cv2.createTrackbar("R_H_lo", "HSV Tuner", int(self.RED_LO[0]), 179, nothing)
        cv2.createTrackbar("R_S_lo", "HSV Tuner", int(self.RED_LO[1]), 255, nothing)
        cv2.createTrackbar("R_V_lo", "HSV Tuner", int(self.RED_LO[2]), 255, nothing)
        cv2.createTrackbar("R_H_hi", "HSV Tuner", int(self.RED_HI[0]), 179, nothing)
        cv2.createTrackbar("R_S_hi", "HSV Tuner", int(self.RED_HI[1]), 255, nothing)
        cv2.createTrackbar("R_V_hi", "HSV Tuner", int(self.RED_HI[2]), 255, nothing)

        # BLUE
        cv2.createTrackbar("B_H_lo", "HSV Tuner", int(self.BLUE_LO[0]), 179, nothing)
        cv2.createTrackbar("B_S_lo", "HSV Tuner", int(self.BLUE_LO[1]), 255, nothing)
        cv2.createTrackbar("B_V_lo", "HSV Tuner", int(self.BLUE_LO[2]), 255, nothing)
        cv2.createTrackbar("B_H_hi", "HSV Tuner", int(self.BLUE_HI[0]), 179, nothing)
        cv2.createTrackbar("B_S_hi", "HSV Tuner", int(self.BLUE_HI[1]), 255, nothing)
        cv2.createTrackbar("B_V_hi", "HSV Tuner", int(self.BLUE_HI[2]), 255, nothing)

    def read_tuner_values(self):
        def g(name):
            return cv2.getTrackbarPos(name, "HSV Tuner")

        self.RED_LO  = np.array([g("R_H_lo"), g("R_S_lo"), g("R_V_lo")], dtype=np.uint8)
        self.RED_HI  = np.array([g("R_H_hi"), g("R_S_hi"), g("R_V_hi")], dtype=np.uint8)
        self.BLUE_LO = np.array([g("B_H_lo"), g("B_S_lo"), g("B_V_lo")], dtype=np.uint8)
        self.BLUE_HI = np.array([g("B_H_hi"), g("B_S_hi"), g("B_V_hi")], dtype=np.uint8)

    def calibrate_from_center_roi(self, frame_bgr, target="RED"):
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
            self.RED_LO, self.RED_HI = lo, hi
            print("[CAL] RED  ->", self.RED_LO.tolist(), self.RED_HI.tolist(), "(wrap if lo>hi)")
        else:
            self.BLUE_LO, self.BLUE_HI = lo, hi
            print("[CAL] BLUE ->", self.BLUE_LO.tolist(), self.BLUE_HI.tolist(), "(wrap if lo>hi)")

    # -------- run loop --------
    def run(self):
        print("[PY] WS_URL:", self.cfg.ws_url, "(disabled)" if self.cfg.no_ws else "")
        cap = self.open_camera()
        self.ws.start()

        fps = 0.0
        prev_t = now()

        preview_name = "Rush Color Agent (STICK) - REF"
        window_open = False
        tuner_open = False

        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                time.sleep(0.01)
                continue

            if self.FLIP_MIRROR:
                frame = cv2.flip(frame, 1)

            if self.BLUR_K and self.BLUR_K >= 3:
                frame = cv2.GaussianBlur(frame, (self.BLUR_K, self.BLUR_K), 0)

            t = now()
            dt = max(1e-6, t - prev_t)
            prev_t = t
            fps = fps * 0.9 + (1.0 / dt) * 0.1

            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

            # tuner
            if self.tuner_on and (not self.cfg.headless):
                if not tuner_open:
                    self.ensure_tuner_window()
                    tuner_open = True
                self.read_tuner_values()
            else:
                if tuner_open:
                    try:
                        cv2.destroyWindow("HSV Tuner")
                    except Exception:
                        pass
                    tuner_open = False

            red_info, red_mask = self.find_marker_tip(hsv, self.RED_LO, self.RED_HI, self.MIN_AREA_RED, self.ASPECT_MIN_STRICT)
            blue_info, blue_mask = self.find_marker_tip(hsv, self.BLUE_LO, self.BLUE_HI, self.MIN_AREA_BLUE, self.ASPECT_MIN_STRICT)

            if red_info is None:
                red_info, red_mask = self.find_marker_tip(hsv, self.RED_LO, self.RED_HI, int(self.MIN_AREA_RED * 0.6), self.ASPECT_MIN_RELAX)
            if blue_info is None:
                blue_info, blue_mask = self.find_marker_tip(hsv, self.BLUE_LO, self.BLUE_HI, int(self.MIN_AREA_BLUE * 0.6), self.ASPECT_MIN_RELAX)

            Hh, Ww = frame.shape[:2]

            red = None
            blue = None

            if red_info:
                tx, ty, area, bbox, ar = red_info
                nx, ny = self.clamp01(tx / Ww), self.clamp01(ty / Hh)
                self.red_seen = t
                self.red_last = (
                    self.ema(self.red_last[0], nx, self.SMOOTH_ALPHA) if self.red_last else nx,
                    self.ema(self.red_last[1], ny, self.SMOOTH_ALPHA) if self.red_last else ny,
                )
                red = {"nx": self.red_last[0], "ny": self.red_last[1], "bbox": bbox}
            else:
                if self.red_last and (t - self.red_seen) <= self.LOSS_GRACE_SEC:
                    red = {"nx": self.red_last[0], "ny": self.red_last[1], "bbox": None}
                else:
                    self.red_last = None

            if blue_info:
                tx, ty, area, bbox, ar = blue_info
                nx, ny = self.clamp01(tx / Ww), self.clamp01(ty / Hh)
                self.blue_seen = t
                self.blue_last = (
                    self.ema(self.blue_last[0], nx, self.SMOOTH_ALPHA) if self.blue_last else nx,
                    self.ema(self.blue_last[1], ny, self.SMOOTH_ALPHA) if self.blue_last else ny,
                )
                blue = {"nx": self.blue_last[0], "ny": self.blue_last[1], "bbox": bbox}
            else:
                if self.blue_last and (t - self.blue_seen) <= self.LOSS_GRACE_SEC:
                    blue = {"nx": self.blue_last[0], "ny": self.blue_last[1], "bbox": None}
                else:
                    self.blue_last = None

            mode_u = str(self.mode).upper()
            rush_ok = bool(self.enabled and mode_u == "RUSH")

            # lane fixed: BLUE=Left, RED=Right
            left_pack = {"gesture": "BLUE", "nx": blue["nx"], "ny": blue["ny"]} if blue else None
            right_pack = {"gesture": "RED", "nx": red["nx"], "ny": red["ny"]} if red else None

            payload = {
                "type": "STATUS",
                "enabled": bool(self.enabled),
                "mode": mode_u,
                "locked": bool(self.locked),
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
                
            # ---- HUD overlay push (local) ----
            hud = getattr(self.cfg, "hud", None)
            if hud:
                # HUD가 읽는 키들(connected/tracking 등)도 같이 채워줌
                hud_payload = dict(payload)
                hud_payload["connected"] = bool(self.ws.connected)
                hud_payload["tracking"] = bool(payload.get("isTracking", False))  # HUD 호환용
                hud_payload["canMove"] = True
                hud_payload["canClick"] = True
                hud_payload["canKey"] = None
                hud.push(hud_payload)

            self.ws.send_dict(payload)
            
            
            if self.cfg.headless:
                time.sleep(0.001)
                continue

            if self.preview:
                if not window_open:
                    cv2.namedWindow(preview_name, cv2.WINDOW_NORMAL)
                    window_open = True

                cv2.putText(
                    frame,
                    f"mode={mode_u} enabled={self.enabled} fps={fps:.1f}  RED={red is not None}  BLUE={blue is not None}",
                    (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2,
                )
                cv2.putText(
                    frame,
                    f"ASPECT strict={self.ASPECT_MIN_STRICT:.2f}/relax={self.ASPECT_MIN_RELAX:.2f}  AREA={self.MIN_AREA_RED}/{self.MIN_AREA_BLUE}  alpha={self.SMOOTH_ALPHA:.2f}",
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
                    self.enabled = not self.enabled
                    print("[KEY] enabled:", self.enabled)
                elif key in (ord("p"), ord("P")):
                    self.preview = not self.preview
                    print("[KEY] PREVIEW:", self.preview)
                elif key in (ord("t"), ord("T")):
                    self.tuner_on = not self.tuner_on
                    print("[KEY] TUNER_ON:", self.tuner_on)
                elif key in (ord("d"), ord("D")):
                    print("[HSV] RED_LO/HI :", self.RED_LO.tolist(), self.RED_HI.tolist(), "(wrap if lo>hi)")
                    print("[HSV] BLUE_LO/HI:", self.BLUE_LO.tolist(), self.BLUE_HI.tolist(), "(wrap if lo>hi)")
                elif key == ord("1"):
                    self.calibrate_from_center_roi(frame, "RED")
                elif key == ord("2"):
                    self.calibrate_from_center_roi(frame, "BLUE")
            else:
                if window_open:
                    try:
                        cv2.destroyWindow(preview_name)
                    except Exception:
                        pass
                    window_open = False
                time.sleep(0.005)

        try:
            cap.release()
        except Exception:
            pass
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
