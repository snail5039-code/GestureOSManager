# gestureos_agent/modes/rush_color.py
# ---------------------------------------------------------------------------
# RUSH_COLOR: OpenCV 색 기반(RED/BLUE) 스틱/포인터 트래킹
#
# 목표
# - 조명/노이즈에 좀 더 강한 트래킹(HSV + optional BGR fallback)
# - 너무 큰 MIN_AREA/ASPECT 조건으로 "아예 못잡는" 상황 방지
# - HandsAgent가 기대하는 형태로 pack(dict: cx/cy)를 반환
#
# 반환
# - process(frame_bgr, t) -> (left_pack, right_pack)
#   left_pack/right_pack: None 또는 {"cx":x01, "cy":y01, "area":float, "color":"BLUE|RED", "ts":t}
# ---------------------------------------------------------------------------

from __future__ import annotations

import os
import math
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List

import cv2
import numpy as np


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


@dataclass
class _MarkerResult:
    cx01: float
    cy01: float
    area: float
    px: float
    py: float


class ColorStickTracker:
    """Detect two colored markers (BLUE=left, RED=right) from a BGR frame."""

    # Default HSV windows (fairly wide)
    # NOTE: Red wraps around hue 0, so we use two ranges (0-12, 165-179) by default.
    BLUE_H_LO = 85
    BLUE_H_HI = 145

    RED_H1_LO = 0
    RED_H1_HI = 12
    RED_H2_LO = 165
    RED_H2_HI = 179

    def __init__(
        self,
        *,
        s_min: int = 60,
        v_min: int = 60,
        min_area: int = 220,
        max_area_frac: float = 0.35,
        morph_kernel: int = 5,
        close_iters: int = 2,
        open_iters: int = 1,
        use_bgr_fallback: bool = True,
        flip_mirror: bool = False,
        smooth_alpha: float = 0.35,
        debug: bool = False,
    ):
        self.s_min = int(s_min)
        self.v_min = int(v_min)
        self.min_area = int(min_area)
        self.max_area_frac = float(max_area_frac)

        k = max(3, int(morph_kernel) | 1)  # odd >=3
        self.kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        self.close_iters = int(close_iters)
        self.open_iters = int(open_iters)

        self.use_bgr_fallback = bool(use_bgr_fallback)
        self.flip_mirror = bool(flip_mirror)
        self.smooth_alpha = float(smooth_alpha)
        self.debug = bool(debug)

        # last stable positions (normalized)
        self._last_blue: Optional[Tuple[float, float]] = None
        self._last_red: Optional[Tuple[float, float]] = None

        # optional debug windows
        self._dbg_name = "[RUSH_COLOR] masks" if self.debug else None

    # ---------------- core helpers ----------------

    def _build_mask_blue(self, hsv: np.ndarray) -> np.ndarray:
        lo = np.array([self.BLUE_H_LO, self.s_min, self.v_min], dtype=np.uint8)
        hi = np.array([self.BLUE_H_HI, 255, 255], dtype=np.uint8)
        return cv2.inRange(hsv, lo, hi)

    def _build_mask_red(self, hsv: np.ndarray) -> np.ndarray:
        lo1 = np.array([self.RED_H1_LO, self.s_min, self.v_min], dtype=np.uint8)
        hi1 = np.array([self.RED_H1_HI, 255, 255], dtype=np.uint8)
        lo2 = np.array([self.RED_H2_LO, self.s_min, self.v_min], dtype=np.uint8)
        hi2 = np.array([self.RED_H2_HI, 255, 255], dtype=np.uint8)
        m1 = cv2.inRange(hsv, lo1, hi1)
        m2 = cv2.inRange(hsv, lo2, hi2)
        return cv2.bitwise_or(m1, m2)

    def _postprocess_mask(self, mask: np.ndarray) -> np.ndarray:
        # denoise (pepper)
        mask = cv2.medianBlur(mask, 5)
        # open -> remove small dots, close -> fill holes
        if self.open_iters > 0:
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel, iterations=self.open_iters)
        if self.close_iters > 0:
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, self.kernel, iterations=self.close_iters)
        return mask

    def _bgr_fallback_mask(self, frame_bgr: np.ndarray, color: str) -> np.ndarray:
        # Very simple channel-dominance fallback when HSV fails under extreme lighting.
        b = frame_bgr[:, :, 0].astype(np.int16)
        g = frame_bgr[:, :, 1].astype(np.int16)
        r = frame_bgr[:, :, 2].astype(np.int16)

        if color == "BLUE":
            m = (b > 120) & (b > g + 35) & (b > r + 35)
        else:  # RED
            m = (r > 120) & (r > g + 35) & (r > b + 35)

        mask = (m.astype(np.uint8) * 255)
        return self._postprocess_mask(mask)

    def _contours_from_mask(self, mask: np.ndarray) -> List[np.ndarray]:
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        return cnts or []

    def _pick_best(
        self,
        contours: List[np.ndarray],
        *,
        w: int,
        h: int,
        last01: Optional[Tuple[float, float]],
    ) -> Optional[_MarkerResult]:
        if not contours:
            return None

        frame_area = float(w * h)
        min_area = max(float(self.min_area), frame_area * 0.00025)  # ~77px @ 640x480
        max_area = frame_area * float(self.max_area_frac)

        # filter candidates
        cands = []
        for c in contours:
            a = float(cv2.contourArea(c))
            if a < min_area or a > max_area:
                continue
            m = cv2.moments(c)
            if abs(m.get("m00", 0.0)) < 1e-6:
                continue
            cx = float(m["m10"] / m["m00"])
            cy = float(m["m01"] / m["m00"])
            cands.append((a, cx, cy, c))

        if not cands:
            return None

        # sort by area desc
        cands.sort(key=lambda t: t[0], reverse=True)

        # if we have last position, prefer near last among top few
        if last01 is not None:
            lx, ly = last01
            lpx = lx * w
            lpy = ly * h
            top = cands[: min(6, len(cands))]
            best = None
            best_d = None
            for a, cx, cy, _ in top:
                d = math.hypot(cx - lpx, cy - lpy)
                if best is None or d < best_d:
                    best = (a, cx, cy)
                    best_d = d
            a, cx, cy = best
        else:
            a, cx, cy, _ = cands[0]

        cx01 = _clamp01(cx / float(w))
        cy01 = _clamp01(cy / float(h))
        return _MarkerResult(cx01=cx01, cy01=cy01, area=a, px=cx, py=cy)

    def _smooth(self, last01: Optional[Tuple[float, float]], cur01: Tuple[float, float]) -> Tuple[float, float]:
        if last01 is None:
            return cur01
        a = self.smooth_alpha
        x = last01[0] * (1.0 - a) + cur01[0] * a
        y = last01[1] * (1.0 - a) + cur01[1] * a
        return (_clamp01(x), _clamp01(y))

    # ---------------- public ----------------

    def process(self, frame_bgr: np.ndarray, t: float) -> Tuple[Optional[Dict], Optional[Dict]]:
        """Return (left_pack(BLUE), right_pack(RED))."""
        if frame_bgr is None:
            return (None, None)

        if self.flip_mirror:
            frame_bgr = cv2.flip(frame_bgr, 1)

        h, w = frame_bgr.shape[:2]
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)

        # BLUE
        mask_b = self._postprocess_mask(self._build_mask_blue(hsv))
        cnts_b = self._contours_from_mask(mask_b)
        blue = self._pick_best(cnts_b, w=w, h=h, last01=self._last_blue)
        if blue is None and self.use_bgr_fallback:
            mask_b = self._bgr_fallback_mask(frame_bgr, "BLUE")
            cnts_b = self._contours_from_mask(mask_b)
            blue = self._pick_best(cnts_b, w=w, h=h, last01=self._last_blue)

        # RED
        mask_r = self._postprocess_mask(self._build_mask_red(hsv))
        cnts_r = self._contours_from_mask(mask_r)
        red = self._pick_best(cnts_r, w=w, h=h, last01=self._last_red)
        if red is None and self.use_bgr_fallback:
            mask_r = self._bgr_fallback_mask(frame_bgr, "RED")
            cnts_r = self._contours_from_mask(mask_r)
            red = self._pick_best(cnts_r, w=w, h=h, last01=self._last_red)

        left_pack = None
        right_pack = None

        if blue is not None:
            bx, by = self._smooth(self._last_blue, (blue.cx01, blue.cy01))
            self._last_blue = (bx, by)
            left_pack = {"cx": bx, "cy": by, "area": float(blue.area), "color": "BLUE", "ts": float(t)}

        if red is not None:
            rx, ry = self._smooth(self._last_red, (red.cx01, red.cy01))
            self._last_red = (rx, ry)
            right_pack = {"cx": rx, "cy": ry, "area": float(red.area), "color": "RED", "ts": float(t)}

        # Optional debug window: show masks side-by-side
        if self.debug:
            try:
                mb = cv2.cvtColor(mask_b, cv2.COLOR_GRAY2BGR)
                mr = cv2.cvtColor(mask_r, cv2.COLOR_GRAY2BGR)
                vis = np.hstack([mb, mr])
                cv2.imshow(self._dbg_name, vis)
                cv2.waitKey(1)
            except Exception:
                pass

        return left_pack, right_pack


# Simple manual test
if __name__ == "__main__":
    cam = int(os.getenv("CAM_INDEX", "0"))
    cap = cv2.VideoCapture(cam)
    tr = ColorStickTracker(debug=True)
    import time
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = time.time()
        lp, rp = tr.process(frame, t)
        # draw
        h, w = frame.shape[:2]
        if lp:
            cv2.circle(frame, (int(lp["cx"] * w), int(lp["cy"] * h)), 10, (255, 0, 0), 2)
        if rp:
            cv2.circle(frame, (int(rp["cx"] * w), int(rp["cy"] * h)), 10, (0, 0, 255), 2)
        cv2.imshow("frame", frame)
        if cv2.waitKey(1) & 0xFF == 27:
            break
    cap.release()
    cv2.destroyAllWindows()
