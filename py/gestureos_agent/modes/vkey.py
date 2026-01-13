from dataclasses import dataclass, field
import subprocess
import pyautogui
from typing import Dict, Optional, Tuple

from ..mathutil import dist_xy, clamp01

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

VKEY_TIPS = [8, 12, 16, 20, 4]  # index > middle > ring > pinky > thumb
VKEY_TIP_TO_PIP = {8: 6, 12: 10, 16: 14, 20: 18, 4: 3}

@dataclass
class AirTapState:
    phase: str = "IDLE"
    t0: float = 0.0
    xy0: Tuple[float, float] = (0.5, 0.5)
    fire_xy: Optional[Tuple[float, float]] = None
    last_fire: float = 0.0
    prev_z: Optional[float] = None
    prev_t: float = 0.0

@dataclass
class VKeyHandler:
    # cooldowns
    per_finger_cooldown: float = 0.18
    global_cooldown: float = 0.10

    # airtap dynamics
    min_gap: float = 0.06
    max_gap: float = 0.22
    z_vel_thresh: float = 0.012
    xy_still_thresh: float = 0.012
    require_extended: bool = True

    tips: list = field(default_factory=lambda: VKEY_TIPS.copy())
    tip_to_pip: dict = field(default_factory=lambda: VKEY_TIP_TO_PIP.copy())

    air_by_tip: Dict[int, AirTapState] = field(default_factory=lambda: {tip: AirTapState() for tip in VKEY_TIPS})
    last_global_fire: float = 0.0

    tap_seq: int = 0
    last_tap: Optional[dict] = None

    def reset(self):
        self.last_global_fire = 0.0
        self.tap_seq = 0
        self.last_tap = None
        for tip in self.tips:
            st = self.air_by_tip[tip]
            st.phase = "IDLE"
            st.t0 = 0.0
            st.xy0 = (0.5, 0.5)
            st.fire_xy = None
            st.last_fire = 0.0
            st.prev_z = None
            st.prev_t = 0.0

    def open_windows_osk(self) -> bool:
        candidates = [
            r"C:\Program Files\Common Files\microsoft shared\ink\TabTip.exe",
            "osk.exe",
        ]
        for cmd in candidates:
            try:
                subprocess.Popen(cmd, shell=True)
                return True
            except Exception:
                pass
        return False

    def _hand_scale(self, lm):
        # wrist(0) to middle_mcp(9)
        return max(1e-6, dist_xy((lm[0][0], lm[0][1]), (lm[9][0], lm[9][1])))

    def _is_tip_extended(self, lm, tip: int) -> bool:
        pip = self.tip_to_pip.get(tip)
        if pip is None:
            return True

        # four fingers: y compare
        if tip in (8, 12, 16, 20):
            return lm[tip][1] < lm[pip][1]

        # thumb: distance heuristic
        return dist_xy((lm[tip][0], lm[tip][1]), (lm[pip][0], lm[pip][1])) > 0.020

    def _airtap_fired_for_tip(self, lm, tip: int, t: float) -> bool:
        st = self.air_by_tip[tip]

        if lm is None:
            st.phase = "IDLE"
            st.prev_z = None
            return False

        if self.require_extended and (not self._is_tip_extended(lm, tip)):
            st.phase = "IDLE"
            return False

        if t < st.last_fire + self.per_finger_cooldown:
            return False

        s = self._hand_scale(lm)
        z = (lm[tip][2] - lm[0][2]) / s
        xy = (lm[tip][0], lm[tip][1])

        if st.prev_z is None:
            st.prev_z = z
            st.prev_t = t
            return False

        dt = max(1e-6, t - st.prev_t)
        dz = (z - st.prev_z) / dt
        st.prev_z = z
        st.prev_t = t

        if st.phase == "IDLE":
            if dz < -self.z_vel_thresh:
                st.phase = "DOWNING"
                st.t0 = t
                st.xy0 = xy
                st.fire_xy = None
            return False

        if st.phase == "DOWNING":
            if dist_xy(xy, st.xy0) > self.xy_still_thresh:
                st.phase = "IDLE"
                return False

            if (t - st.t0) > self.max_gap:
                st.phase = "IDLE"
                return False

            if dz > self.z_vel_thresh:
                gap = t - st.t0
                st.phase = "IDLE"
                if self.min_gap <= gap <= self.max_gap:
                    st.last_fire = t
                    st.fire_xy = st.xy0
                    return True
            return False

        st.phase = "IDLE"
        return False

    def update(self, t: float, can_inject_os_click: bool, cursor_lm, map_control_to_screen):
        """
        - detects AirTap and creates tap event fields (tap_seq/last_tap)
        - if can_inject_os_click: performs OS click at mapped position
        """
        if cursor_lm is None:
            for tip in self.tips:
                self.air_by_tip[tip].phase = "IDLE"
            return

        if t < self.last_global_fire + self.global_cooldown:
            return

        fired_tip = None
        for tip in self.tips:
            if self._airtap_fired_for_tip(cursor_lm, tip, t):
                fired_tip = tip
                break

        if fired_tip is None:
            return

        st = self.air_by_tip[fired_tip]
        px, py = st.fire_xy if st.fire_xy is not None else (cursor_lm[fired_tip][0], cursor_lm[fired_tip][1])

        ux, uy = map_control_to_screen(px, py)

        self.tap_seq += 1
        self.last_tap = {"seq": self.tap_seq, "x": float(ux), "y": float(uy), "finger": int(fired_tip), "ts": float(t)}

        if can_inject_os_click:
            sx, sy = pyautogui.size()
            x = int(ux * sx)
            y = int(uy * sy)
            try:
                pyautogui.click(x=x, y=y)
            except Exception:
                pass

        self.last_global_fire = t
