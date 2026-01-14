# gestureos_agent/modes/rush_color.py
import cv2
import numpy as np
from typing import Optional, Tuple, Dict, Any


class ColorStickTracker:
    """
    Color stick tracker extracted from ColorRushAgent, but:
    - NO camera loop
    - NO WS
    - Pure function style: process(frame_bgr, t) -> (left_pack, right_pack)

    Return packs format (HandsAgent 호환):
      left_pack  = {"gesture":"BLUE", "cx":x01, "cy":y01}
      right_pack = {"gesture":"RED",  "cx":x01, "cy":y01}
    """

    FRAME_W = 640
    FRAME_H = 480
    FLIP_MIRROR = False  # HandsAgent에서 이미 flip(frame,1) 하고 있으면 False

    MIN_AREA_RED = 1800
    MIN_AREA_BLUE = 1800
    MAX_AREA = 160000

    LOSS_GRACE_SEC = 0.22
    SMOOTH_ALPHA = 0.75

    ASPECT_MIN_STRICT = 2.0
    ASPECT_MIN_RELAX = 1.45

    BLUR_K = 3

    BLUE_LO = np.array([95, 70, 60], dtype=np.uint8)
    BLUE_HI = np.array([140, 255, 255], dtype=np.uint8)

    # RED hue wrap (lo>hi 가능)
    RED_LO = np.array([170, 120, 80], dtype=np.uint8)
    RED_HI = np.array([10, 255, 255], dtype=np.uint8)

    def __init__(self):
        self.kernel = np.ones((5, 5), np.uint8)

        self.red_last: Optional[Tuple[float, float]] = None
        self.blue_last: Optional[Tuple[float, float]] = None
        self.red_seen = 0.0
        self.blue_seen = 0.0

        # (선택) 튜너 훅 - 필요하면 HandsAgent에서 키로 열어도 됨
        self.tuner_on = False
        self._tuner_open = False

    # ---------------- helpers ----------------
    @staticmethod
    def clamp01(v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    @staticmethod
    def ema(prev: Optional[float], cur: float, a: float) -> float:
        if prev is None:
            return cur
        return (1 - a) * prev + a * cur

    def build_mask(self, hsv, lo, hi):
        loH, loS, loV = int(lo[0]), int(lo[1]), int(lo[2])
        hiH, hiS, hiV = int(hi[0]), int(hi[1]), int(hi[2])

        # normal
        if loH <= hiH:
            return cv2.inRange(
                hsv,
                np.array([loH, loS, loV], np.uint8),
                np.array([hiH, hiS, hiV], np.uint8),
            )

        # wrap-around (e.g. red)
        m1 = cv2.inRange(hsv, np.array([loH, loS, loV], np.uint8), np.array([179, hiS, hiV], np.uint8))
        m2 = cv2.inRange(hsv, np.array([0, loS, loV], np.uint8), np.array([hiH, hiS, hiV], np.uint8))
        return cv2.bitwise_or(m1, m2)

    @staticmethod
    def contour_aspect_ratio(c) -> float:
        rect = cv2.minAreaRect(c)
        (w, h) = rect[1]
        w = float(w)
        h = float(h)
        short = max(1e-6, min(w, h))
        longv = max(w, h)
        return longv / short

    @staticmethod
    def contour_topmost_point(c) -> Tuple[float, float]:
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

    # ---------------- optional tuner ----------------
    def _ensure_tuner_window(self):
        cv2.namedWindow("HSV Tuner", cv2.WINDOW_NORMAL)

        def nothing(_):
            pass

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

    def _read_tuner_values(self):
        def g(name):
            return cv2.getTrackbarPos(name, "HSV Tuner")

        self.RED_LO = np.array([g("R_H_lo"), g("R_S_lo"), g("R_V_lo")], dtype=np.uint8)
        self.RED_HI = np.array([g("R_H_hi"), g("R_S_hi"), g("R_V_hi")], dtype=np.uint8)
        self.BLUE_LO = np.array([g("B_H_lo"), g("B_S_lo"), g("B_V_lo")], dtype=np.uint8)
        self.BLUE_HI = np.array([g("B_H_hi"), g("B_S_hi"), g("B_V_hi")], dtype=np.uint8)

    def toggle_tuner(self):
        self.tuner_on = not self.tuner_on
        if not self.tuner_on and self._tuner_open:
            try:
                cv2.destroyWindow("HSV Tuner")
            except Exception:
                pass
            self._tuner_open = False

    def print_hsv(self):
        print("[HSV] RED_LO/HI :", self.RED_LO.tolist(), self.RED_HI.tolist(), "(wrap if lo>hi)")
        print("[HSV] BLUE_LO/HI:", self.BLUE_LO.tolist(), self.BLUE_HI.tolist(), "(wrap if lo>hi)")

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

    # ---------------- main API ----------------
    def process(self, frame_bgr, t: float):
        """
        Returns:
          (left_pack, right_pack)
          left_pack  => BLUE
          right_pack => RED
        """
        if frame_bgr is None:
            return None, None

        frame = frame_bgr

        if self.FLIP_MIRROR:
            frame = cv2.flip(frame, 1)

        if self.BLUR_K and self.BLUR_K >= 3:
            frame = cv2.GaussianBlur(frame, (self.BLUR_K, self.BLUR_K), 0)

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # tuner (optional)
        if self.tuner_on:
            if not self._tuner_open:
                self._ensure_tuner_window()
                self._tuner_open = True
            self._read_tuner_values()
        else:
            if self._tuner_open:
                try:
                    cv2.destroyWindow("HSV Tuner")
                except Exception:
                    pass
                self._tuner_open = False

        red_info, _ = self.find_marker_tip(hsv, self.RED_LO, self.RED_HI, self.MIN_AREA_RED, self.ASPECT_MIN_STRICT)
        blue_info, _ = self.find_marker_tip(hsv, self.BLUE_LO, self.BLUE_HI, self.MIN_AREA_BLUE, self.ASPECT_MIN_STRICT)

        if red_info is None:
            red_info, _ = self.find_marker_tip(hsv, self.RED_LO, self.RED_HI, int(self.MIN_AREA_RED * 0.6), self.ASPECT_MIN_RELAX)
        if blue_info is None:
            blue_info, _ = self.find_marker_tip(hsv, self.BLUE_LO, self.BLUE_HI, int(self.MIN_AREA_BLUE * 0.6), self.ASPECT_MIN_RELAX)

        Hh, Ww = frame.shape[:2]

        red = None
        blue = None

        # RED -> right
        if red_info:
            tx, ty, _, _, _ = red_info
            nx, ny = self.clamp01(tx / Ww), self.clamp01(ty / Hh)
            self.red_seen = t
            self.red_last = (
                self.ema(self.red_last[0] if self.red_last else None, nx, self.SMOOTH_ALPHA),
                self.ema(self.red_last[1] if self.red_last else None, ny, self.SMOOTH_ALPHA),
            )
            red = {"cx": self.red_last[0], "cy": self.red_last[1]}
        else:
            if self.red_last and (t - self.red_seen) <= self.LOSS_GRACE_SEC:
                red = {"cx": self.red_last[0], "cy": self.red_last[1]}
            else:
                self.red_last = None

        # BLUE -> left
        if blue_info:
            tx, ty, _, _, _ = blue_info
            nx, ny = self.clamp01(tx / Ww), self.clamp01(ty / Hh)
            self.blue_seen = t
            self.blue_last = (
                self.ema(self.blue_last[0] if self.blue_last else None, nx, self.SMOOTH_ALPHA),
                self.ema(self.blue_last[1] if self.blue_last else None, ny, self.SMOOTH_ALPHA),
            )
            blue = {"cx": self.blue_last[0], "cy": self.blue_last[1]}
        else:
            if self.blue_last and (t - self.blue_seen) <= self.LOSS_GRACE_SEC:
                blue = {"cx": self.blue_last[0], "cy": self.blue_last[1]}
            else:
                self.blue_last = None

        left_pack = {"gesture": "BLUE", "cx": blue["cx"], "cy": blue["cy"]} if blue else None
        right_pack = {"gesture": "RED", "cx": red["cx"], "cy": red["cy"]} if red else None
        return left_pack, right_pack
