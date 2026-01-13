from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from ..gestures import palm_center, classify_gesture

@dataclass
class RushLRPicker:
    deadband: float = 0.06
    swap_frames: int = 4
    onehand_keep_sec: float = 0.25

    state: dict = None
    last_twohand_ts: float = 0.0

    def __post_init__(self):
        if self.state is None:
            self.state = {"left": None, "right": None, "pending_swap": 0}

    def reset(self):
        self.state["left"] = None
        self.state["right"] = None
        self.state["pending_swap"] = 0
        self.last_twohand_ts = 0.0

    def _pack(self, lm):
        cx, cy = palm_center(lm)
        return {"cx": cx, "cy": cy, "gesture": classify_gesture(lm)}

    def _dist2(self, a, b):
        if a is None or b is None:
            return 1e9
        dx = a["cx"] - b["cx"]
        dy = a["cy"] - b["cy"]
        return dx * dx + dy * dy

    def pick(self, t: float, hands_list: List[Tuple[str | None, Any]]):
        """
        hands_list: [(label, lm), ...]
        Returns (left_pack, right_pack) where each pack is dict(cx,cy,gesture)
        """
        if not hands_list:
            self.reset()
            return None, None

        packs = []
        for label, lm in hands_list:
            if lm is None:
                continue
            packs.append(self._pack(lm))

        if not packs:
            return None, None

        if len(packs) == 1:
            p = packs[0]
            if t - self.last_twohand_ts < self.onehand_keep_sec:
                dl = self._dist2(p, self.state["left"])
                dr = self._dist2(p, self.state["right"])
                if dl < dr:
                    self.state["left"] = p
                    return self.state["left"], self.state["right"]
                else:
                    self.state["right"] = p
                    return self.state["left"], self.state["right"]

            self.state["left"] = None
            self.state["right"] = p
            self.state["pending_swap"] = 0
            return None, p

        packs.sort(key=lambda p: p["cx"])
        left_now = packs[0]
        right_now = packs[-1]
        self.last_twohand_ts = t

        if self.state["left"] is None and self.state["right"] is None:
            self.state["left"] = left_now
            self.state["right"] = right_now
            self.state["pending_swap"] = 0
            return self.state["left"], self.state["right"]

        if abs(right_now["cx"] - left_now["cx"]) < self.deadband:
            cost_keep = self._dist2(left_now, self.state["left"]) + self._dist2(right_now, self.state["right"])
            cost_swap = self._dist2(left_now, self.state["right"]) + self._dist2(right_now, self.state["left"])
            if cost_swap < cost_keep:
                self.state["left"] = right_now
                self.state["right"] = left_now
            else:
                self.state["left"] = left_now
                self.state["right"] = right_now
            self.state["pending_swap"] = 0
            return self.state["left"], self.state["right"]

        cost_keep = self._dist2(left_now, self.state["left"]) + self._dist2(right_now, self.state["right"])
        cost_swap = self._dist2(left_now, self.state["right"]) + self._dist2(right_now, self.state["left"])
        want_swap = (cost_swap + 1e-9) < cost_keep

        if want_swap:
            self.state["pending_swap"] += 1
            if self.state["pending_swap"] >= self.swap_frames:
                self.state["left"] = right_now
                self.state["right"] = left_now
                self.state["pending_swap"] = 0
        else:
            self.state["pending_swap"] = 0
            self.state["left"] = left_now
            self.state["right"] = right_now

        return self.state["left"], self.state["right"]
