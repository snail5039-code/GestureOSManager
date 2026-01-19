import os
import json
import time
import math
from typing import Dict, List, Optional, Tuple, Any

MODEL_PATH = os.path.join(os.getenv("TEMP", "."), "GestureOS_learner.json")
MAX_SAMPLES_PER_LABEL = 600


def _l2(a: List[float], b: List[float]) -> float:
    s = 0.0
    for i in range(len(a)):
        d = a[i] - b[i]
        s += d * d
    return math.sqrt(s)


class ProtoLearner:
    def __init__(self, model_path: str = MODEL_PATH):
        self.model_path = model_path

        self.enabled: bool = False
        self.min_samples: int = 10
        self.min_conf: float = 0.55

        # samples[hand][label] = [vec, vec, ...]
        self.samples: Dict[str, Dict[str, List[List[float]]]] = {"cursor": {}, "other": {}}

        # model[hand][label] = {"centroid":[...], "sigma":float, "n":int}
        self.model: Dict[str, Dict[str, Dict[str, Any]]] = {"cursor": {}, "other": {}}

        self.last_pred: Optional[dict] = None
        self.last_train_ts: Optional[float] = None

        # capture state
        self.capture: Optional[dict] = None

        self.load()

    def extract(self, lm) -> Optional[List[float]]:
        """lm: [(x,y,z), ...] length 21"""
        if not lm or len(lm) != 21:
            return None

        x0, y0, z0 = lm[0]
        pts = [(x - x0, y - y0, z - z0) for (x, y, z) in lm]

        sx, sy, sz = pts[9]  # middle_mcp
        scale = math.sqrt(sx * sx + sy * sy + sz * sz)
        if scale < 1e-6:
            scale = max((math.sqrt(x*x + y*y + z*z) for (x, y, z) in pts), default=1.0)
            if scale < 1e-6:
                scale = 1.0

        inv = 1.0 / scale
        vec: List[float] = []
        for (x, y, z) in pts:
            vec.extend([x * inv, y * inv, z * inv])
        return vec

    def _ensure(self, hand: str, label: str):
        hand = "cursor" if hand != "other" else "other"
        self.samples.setdefault(hand, {})
        self.samples[hand].setdefault(label, [])

    def add_sample(self, hand: str, label: str, lm) -> bool:
        vec = self.extract(lm)
        if vec is None:
            return False
        hand = "cursor" if hand != "other" else "other"
        self._ensure(hand, label)
        arr = self.samples[hand][label]
        arr.append(vec)
        if len(arr) > MAX_SAMPLES_PER_LABEL:
            del arr[: len(arr) - MAX_SAMPLES_PER_LABEL]
        return True

    def counts(self) -> Dict[str, Dict[str, int]]:
        out: Dict[str, Dict[str, int]] = {}
        for hand, mp in self.samples.items():
            out[hand] = {lab: len(vs) for lab, vs in mp.items()}
        return out

    def train(self):
        self.model = {"cursor": {}, "other": {}}

        for hand, mp in self.samples.items():
            for label, vecs in mp.items():
                if len(vecs) < self.min_samples:
                    continue
                dim = len(vecs[0])
                c = [0.0] * dim
                for v in vecs:
                    for i in range(dim):
                        c[i] += v[i]
                n = float(len(vecs))
                for i in range(dim):
                    c[i] /= n

                # sigma = RMS distance
                s2 = 0.0
                for v in vecs:
                    d = _l2(v, c)
                    s2 += d * d
                s2 /= max(1.0, n)
                sigma = math.sqrt(s2) + 1e-6

                self.model[hand][label] = {
                    "centroid": c,
                    "sigma": float(sigma),
                    "n": int(n),
                }

        self.last_train_ts = time.time()
        self.save()

    def predict(self, hand: str, lm) -> Tuple[Optional[str], float]:
        if not self.enabled:
            return None, 0.0

        vec = self.extract(lm)
        if vec is None:
            return None, 0.0

        hand = "cursor" if hand != "other" else "other"
        models = self.model.get(hand) or {}
        if not models:
            return None, 0.0

        best_label = None
        best_score = 0.0

        for label, m in models.items():
            c = m.get("centroid")
            sigma = float(m.get("sigma", 1.0))
            if not c:
                continue
            dist = _l2(vec, c)
            score = math.exp(-dist / (sigma + 1e-6))
            if score > best_score:
                best_score = score
                best_label = label

        if best_label is None or best_score < self.min_conf:
            return None, float(best_score)

        return best_label, float(best_score)

    def start_capture(self, hand: str, label: str, seconds: float = 2.0, hz: int = 15):
        hand = "cursor" if hand != "other" else "other"
        hz = max(1, int(hz))
        seconds = max(0.3, float(seconds))

        now = time.time()
        self.capture = {
            "hand": hand,
            "label": str(label),
            "until": now + seconds,
            "interval": 1.0 / hz,
            "next": 0.0,
            "collected": 0,
        }

    def tick_capture(self, cursor_lm, other_lm):
        if not self.capture:
            return

        now = time.time()
        if now >= float(self.capture.get("until", 0.0)):
            self.capture = None
            return

        if float(self.capture.get("next", 0.0)) == 0.0:
            self.capture["next"] = now

        if now < float(self.capture["next"]):
            return

        self.capture["next"] = now + float(self.capture["interval"])

        hand = self.capture["hand"]
        label = self.capture["label"]
        lm = cursor_lm if hand == "cursor" else other_lm
        if lm is None:
            return

        ok = self.add_sample(hand, label, lm)
        if ok:
            self.capture["collected"] = int(self.capture.get("collected", 0)) + 1

    def reset(self):
        self.samples = {"cursor": {}, "other": {}}
        self.model = {"cursor": {}, "other": {}}
        self.last_pred = None
        self.last_train_ts = None
        self.capture = None
        self.save()

    def save(self):
        try:
            obj = {
                "enabled": bool(self.enabled),
                "min_samples": int(self.min_samples),
                "min_conf": float(self.min_conf),
                "last_train_ts": self.last_train_ts,
                "counts": self.counts(),
                "model": self.model,  # centroid만 저장 (samples는 안 저장)
            }
            with open(self.model_path, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False)
        except Exception:
            pass

    def load(self):
        try:
            if not os.path.exists(self.model_path):
                return
            with open(self.model_path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            self.enabled = bool(obj.get("enabled", False))
            self.min_samples = int(obj.get("min_samples", self.min_samples))
            self.min_conf = float(obj.get("min_conf", self.min_conf))
            self.last_train_ts = obj.get("last_train_ts", None)
            self.model = obj.get("model", self.model) or self.model
        except Exception:
            pass
