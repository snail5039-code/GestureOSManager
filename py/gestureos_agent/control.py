from dataclasses import dataclass
from typing import Optional, Tuple

import pyautogui

from .mathutil import clamp01

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

@dataclass
class ControlMapper:
    control_box: Tuple[float, float, float, float]
    gain: float
    ema_alpha: float
    deadzone_px: int
    move_interval_sec: float

    ema_x: Optional[float] = None
    ema_y: Optional[float] = None
    last_move_ts: float = 0.0

    def reset_ema(self):
        self.ema_x = None
        self.ema_y = None

    def map_control_to_screen(self, cx: float, cy: float) -> Tuple[float, float]:
        minx, miny, maxx, maxy = self.control_box
        ux = (cx - minx) / max(1e-6, (maxx - minx))
        uy = (cy - miny) / max(1e-6, (maxy - miny))
        ux = clamp01(ux)
        uy = clamp01(uy)
        ux = 0.5 + (ux - 0.5) * self.gain
        uy = 0.5 + (uy - 0.5) * self.gain
        return clamp01(ux), clamp01(uy)

    def apply_ema(self, nx: float, ny: float) -> Tuple[float, float]:
        if self.ema_x is None:
            self.ema_x, self.ema_y = nx, ny
        else:
            a = self.ema_alpha
            self.ema_x = a * nx + (1.0 - a) * self.ema_x
            self.ema_y = a * ny + (1.0 - a) * self.ema_y
        return self.ema_x, self.ema_y

    def move_cursor(self, norm_x: float, norm_y: float, now_ts: float):
        if (now_ts - self.last_move_ts) < self.move_interval_sec:
            return
        self.last_move_ts = now_ts

        sx, sy = pyautogui.size()
        x = int(norm_x * sx)
        y = int(norm_y * sy)

        cur = pyautogui.position()
        if abs(x - cur.x) < self.deadzone_px and abs(y - cur.y) < self.deadzone_px:
            return

        pyautogui.moveTo(x, y)
